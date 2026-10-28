"""Parse web access logs and rank endpoints by server error (HTTP 5xx).

Techniques from the explainer "Find the Top Error Endpoints in Web Logs":

* compile one named-group regex, and offer a ``str.split`` fast path
* count malformed lines and skip them, and never crash on a bad line
* rank paths with ``Counter`` and ``heapq``
* normalize IDs (``/api/orders/123`` -> ``/api/orders/{id}``) before ranking
* rank by error rate with a minimum request threshold
* keep an incident window, and bucket requests by time
* stream plain and gzip files one line at a time
* optionally count files (or chunks of one plain file) in a process pool
  and merge the Counters with ``sum``

Run ``python -m opskit.logs access.log`` for a short report.
"""
from __future__ import annotations

import argparse
import gzip
import heapq
import json
import re
import sys
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from multiprocessing import Pool
from pathlib import Path
from typing import IO, Literal, NamedTuple

ParserName = Literal["regex", "split"]

# Compiled once. Named groups cover the Common Log fields the original
# solution needs (method, path, status, size) plus the surrounding ones.
ACCESS_LOG_RE = re.compile(
    r"(?P<ip>\S+) "
    r"(?P<ident>\S+) "
    r"(?P<user>\S+) "
    r"\[(?P<time>[^\]]+)\] "
    r'"(?P<method>\S+) (?P<path>\S+) (?P<protocol>[^"]*)" '
    r"(?P<status>\d{3}) "
    r"(?P<size>\S+)"
)
_TIME_FORMAT = "%d/%b/%Y:%H:%M:%S %z"
# Whitespace split of a Common Log line. The timestamp contains a space,
# so the path is field 6 and the status is field 8:
#   0:ip 1:ident 2:user 3:[date 4:+0000] 5:"METHOD 6:path 7:HTTP/1.1" 8:status 9:size
_MIN_FIELDS = 10
_PATH_FIELD = 6
_STATUS_FIELD = 8
_ID_PLACEHOLDER = "{id}"
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


@dataclass(frozen=True)
class AccessRecord:
    """One parsed access-log request. ``status`` stays a string so 5xx is a prefix check."""

    ip: str
    ident: str
    user: str
    time: str
    timestamp: datetime
    method: str
    path: str
    protocol: str
    status: str
    size: str


class RankedErrors(NamedTuple):
    """Top endpoints and how many lines were malformed.

    Unpack it (``ranking, bad = ...``) or use ``.ranking`` and ``.bad``.
    """

    ranking: list[tuple[str, int]]
    bad: int


@dataclass(frozen=True)
class ErrorRate:
    """Server errors divided by total requests for one normalized endpoint."""

    endpoint: str
    errors: int
    requests: int

    @property
    def rate(self) -> float:
        if self.requests == 0:
            return 0.0
        return self.errors / self.requests

    @property
    def percent(self) -> str:
        """One decimal place. 12 errors in 98 requests is ``12.2%``."""
        return f"{self.rate * 100:.1f}%"


@dataclass(frozen=True)
class WindowBucket:
    """Requests and 5xx errors whose timestamps fall in ``[start, start + window)``."""

    start: datetime
    errors: int
    requests: int

    @property
    def rate(self) -> float:
        if self.requests == 0:
            return 0.0
        return self.errors / self.requests


@dataclass
class EndpointStats:
    """Aggregated counts. ``errors`` counts 5xx only; ``requests`` counts every parsed line."""

    errors: Counter[str]
    requests: Counter[str]
    bad: int

    def top_errors(self, n: int = 5) -> list[tuple[str, int]]:
        """Return the ``n`` endpoints with the most 5xx responses, using ``heapq``."""
        if n < 1:
            raise ValueError("n must be >= 1")
        return heapq.nlargest(n, self.errors.items(), key=lambda item: item[1])

    def error_rates(self, n: int = 5, min_requests: int = 1) -> list[ErrorRate]:
        """Rank by errors/requests. Endpoints below ``min_requests`` are left out.

        The minimum exists so one request with one error does not show up as 100%.
        """
        if n < 1:
            raise ValueError("n must be >= 1")
        if min_requests < 1:
            raise ValueError("min_requests must be >= 1")
        eligible = [
            ErrorRate(endpoint, self.errors[endpoint], total)
            for endpoint, total in self.requests.items()
            if total >= min_requests
        ]
        eligible.sort(key=lambda row: (-row.rate, -row.errors, row.endpoint))
        return eligible[:n]

    @property
    def request_count(self) -> int:
        return sum(self.requests.values())


def parse_named(line: str) -> dict[str, str] | None:
    """Return every named group, or None when the line is not an access-log record."""
    match = ACCESS_LOG_RE.match(line.strip())
    if match is None:
        return None
    return match.groupdict()


def parse_split(line: str) -> tuple[str, str] | None:
    """Return ``(path, status)`` or None.

    Fast path for a fixed layout: at least 10 fields and a numeric status.
    Field 6 is the path and field 8 is the status, because the timestamp
    itself contains a space. Garbage returns None.
    """
    fields = line.split()
    if len(fields) < _MIN_FIELDS:
        return None
    status = fields[_STATUS_FIELD]
    if not status.isdigit():
        return None
    return fields[_PATH_FIELD], status


def parse_line(line: str) -> AccessRecord | None:
    """Parse one line into a record, or None if it is malformed or the time is not.

    Uses the named-group regex. A line that matches the shape but whose timestamp
    does not parse is bad input, not an exception.
    """
    fields = parse_named(line)
    if fields is None:
        return None
    try:
        timestamp = datetime.strptime(fields["time"], _TIME_FORMAT)
    except ValueError:
        return None
    return AccessRecord(
        ip=fields["ip"],
        ident=fields["ident"],
        user=fields["user"],
        time=fields["time"],
        timestamp=timestamp,
        method=fields["method"],
        path=fields["path"],
        protocol=fields["protocol"],
        status=fields["status"],
        size=fields["size"],
    )


def is_server_error(status: str | int) -> bool:
    """True for HTTP 5xx. 4xx is a client error and does not count."""
    return str(status).startswith("5")


def normalize_endpoint(path: str) -> str:
    """Drop the query string and replace all-digit segments with ``{id}``.

    ``/api/users/123`` and ``/api/orders/17?x=1`` both collapse so each id
    is not ranked as its own endpoint.
    """
    path = path.split("?", 1)[0]
    parts = [_ID_PLACEHOLDER if segment.isdigit() else segment for segment in path.split("/")]
    return "/".join(parts)


def _endpoint(path: str, normalize: bool) -> str:
    return normalize_endpoint(path) if normalize else path


def _check_parser(parser: str) -> ParserName:
    if parser == "regex":
        return "regex"
    if parser == "split":
        return "split"
    raise ValueError("parser must be 'regex' or 'split'")


def _accumulate(stats: EndpointStats, line: str, *, normalize: bool, parser: ParserName) -> None:
    if parser == "split":
        parsed = parse_split(line)
        if parsed is None:
            stats.bad += 1
            return
        path, status = parsed
    else:
        record = parse_line(line)
        if record is None:
            stats.bad += 1
            return
        path, status = record.path, record.status
    endpoint = _endpoint(path, normalize)
    stats.requests[endpoint] += 1
    if is_server_error(status):
        stats.errors[endpoint] += 1


def scan_lines(
    lines: Iterable[str],
    *,
    normalize: bool = False,
    parser: ParserName = "regex",
) -> EndpointStats:
    """Count endpoints in ``lines``. Malformed lines increment ``bad`` and are skipped."""
    chosen = _check_parser(parser)
    stats = EndpointStats(Counter(), Counter(), 0)
    for line in lines:
        _accumulate(stats, line, normalize=normalize, parser=chosen)
    return stats


def top_error_endpoints(
    lines: Iterable[str],
    n: int = 5,
    *,
    normalize: bool = False,
    parser: ParserName = "regex",
) -> RankedErrors:
    """Return the top ``n`` endpoints by 5xx count, plus the malformed-line count.

    Statuses that start with ``5`` are server errors. Set ``normalize=True``
    so ``/api/orders/123`` and ``/api/orders/456`` count as one endpoint.
    ``parser='split'`` is the fast path when the log layout is fixed.
    """
    stats = scan_lines(lines, normalize=normalize, parser=parser)
    return RankedErrors(stats.top_errors(n), stats.bad)


def error_rates(
    lines: Iterable[str],
    n: int = 5,
    *,
    min_requests: int = 1,
    normalize: bool = True,
    parser: ParserName = "regex",
) -> list[ErrorRate]:
    """Rank endpoints by 5xx rate (errors / requests), ignoring low-traffic paths.

    Busy endpoints win a pure count. Dividing by total requests, and requiring
    ``min_requests``, keeps a single failure from ranking as 100%.
    """
    stats = scan_lines(lines, normalize=normalize, parser=parser)
    return stats.error_rates(n, min_requests)


def iter_records(lines: Iterable[str]) -> Iterator[AccessRecord]:
    """Yield parsed records and skip malformed lines. One pass, no list."""
    for line in lines:
        record = parse_line(line)
        if record is not None:
            yield record


def _as_utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def after_cutoff(records: Iterable[AccessRecord], cutoff: datetime) -> Iterator[AccessRecord]:
    """Yield records strictly after ``cutoff``."""
    cutoff_utc = _as_utc(cutoff)
    for record in records:
        if _as_utc(record.timestamp) > cutoff_utc:
            yield record


def recent(
    records: Iterable[AccessRecord],
    *,
    minutes: int,
    now: datetime | None = None,
) -> Iterator[AccessRecord]:
    """Yield records from the last ``minutes`` before ``now``.

    ``now`` defaults to the latest timestamp, which reads the whole iterable
    first. Pass ``now`` to keep this a streaming generator during an incident.
    Records are yielded only when their timestamp is after the cutoff.
    """
    if minutes < 0:
        raise ValueError("minutes must be >= 0")
    if now is None:
        records = list(records)
        if not records:
            return
        now = max(_as_utc(record.timestamp) for record in records)
    cutoff = _as_utc(now) - timedelta(minutes=minutes)
    yield from after_cutoff(records, cutoff)


def bucket_by_time(
    records: Iterable[AccessRecord],
    window: timedelta = timedelta(minutes=1),
) -> list[WindowBucket]:
    """Bucket records into fixed UTC windows and count requests and 5xx errors.

    Empty windows are omitted. Buckets are ordered by start time.
    """
    width = int(window.total_seconds())
    if width < 1:
        raise ValueError("window must be at least 1 second")
    errors: dict[datetime, int] = {}
    totals: dict[datetime, int] = {}
    for record in records:
        seconds = int((_as_utc(record.timestamp) - _EPOCH).total_seconds())
        start = _EPOCH + timedelta(seconds=seconds - (seconds % width))
        totals[start] = totals.get(start, 0) + 1
        if is_server_error(record.status):
            errors[start] = errors.get(start, 0) + 1
    return [
        WindowBucket(start=start, errors=errors.get(start, 0), requests=total)
        for start, total in sorted(totals.items())
    ]


def open_log(path: str | Path) -> IO[str]:
    """Open a log for text reading. ``.gz`` files use ``gzip.open``."""
    file_path = Path(path)
    if file_path.suffix.lower() == ".gz":
        return gzip.open(file_path, "rt", encoding="utf-8", errors="replace")
    return file_path.open("rt", encoding="utf-8", errors="replace")


def read_lines(path: str | Path) -> Iterator[str]:
    """Yield one line at a time so a large file does not have to sit in memory.

    The file stays open until the generator is exhausted or closed.
    """
    with open_log(path) as handle:
        for line in handle:
            yield line.rstrip("\r\n")


def count_file(
    path: str | Path,
    *,
    normalize: bool = False,
    parser: ParserName = "regex",
) -> EndpointStats:
    """Stream one plain or gzip log and count endpoints."""
    return scan_lines(read_lines(path), normalize=normalize, parser=parser)


def merge_counters(counters: Iterable[Counter[str]]) -> Counter[str]:
    """Merge Counters by addition. ``Counter`` implements ``+``, so ``sum`` merges them."""
    return sum(counters, Counter())


def merge_stats(parts: Iterable[EndpointStats]) -> EndpointStats:
    """Add per-file stats into one result. Counters merge with ``sum``."""
    items = list(parts)
    return EndpointStats(
        errors=merge_counters(part.errors for part in items),
        requests=merge_counters(part.requests for part in items),
        bad=sum(part.bad for part in items),
    )


def _count_file_spec(spec: tuple[str, bool, ParserName]) -> EndpointStats:
    path, normalize, parser = spec
    return count_file(path, normalize=normalize, parser=parser)


def _line_spans(path: str, chunks: int) -> list[tuple[int, int]]:
    """Split a plain file into ``chunks`` byte ranges that fall on line boundaries."""
    size = Path(path).stat().st_size
    if chunks <= 1 or size == 0:
        return [(0, size)]
    spans: list[tuple[int, int]] = []
    start = 0
    with open(path, "rb") as handle:
        for index in range(chunks - 1):
            target = size * (index + 1) // chunks
            if target <= start:
                continue
            handle.seek(target)
            handle.readline()  # finish the partial line; it stays in this span
            end = handle.tell()
            if end >= size:
                break
            spans.append((start, end))
            start = end
    spans.append((start, size))
    return spans


def _count_span(spec: tuple[str, int, int, bool, ParserName]) -> EndpointStats:
    path, start, end, normalize, parser = spec
    stats = EndpointStats(Counter(), Counter(), 0)
    with open(path, "rb") as handle:
        handle.seek(start)
        while handle.tell() < end:
            raw = handle.readline()
            if not raw:
                break
            _accumulate(stats, raw.decode("utf-8", "replace"), normalize=normalize, parser=parser)
    return stats


def _is_gzip(path: str) -> bool:
    return Path(path).suffix.lower() == ".gz"


def count_files(
    paths: Sequence[str | Path],
    *,
    normalize: bool = False,
    parser: ParserName = "regex",
    workers: int = 1,
) -> EndpointStats:
    """Count logs, optionally in a process pool, and merge the Counters.

    ``workers`` 1 stays in-process. Several files are mapped one file per
    process (the pool size is ``min(workers, len(paths))``). A single plain
    file with ``workers`` > 1 is split on line boundaries and counted in
    parallel; gzip is always streamed in one process because it does not
    split on byte offsets.
    """
    if workers < 1:
        raise ValueError("workers must be >= 1")
    chosen = _check_parser(parser)
    files = [str(path) for path in paths]
    if not files:
        return EndpointStats(Counter(), Counter(), 0)
    if workers == 1 or (len(files) == 1 and _is_gzip(files[0])):
        return merge_stats(count_file(path, normalize=normalize, parser=chosen) for path in files)
    if len(files) == 1:
        spans = [
            (files[0], start, end, normalize, chosen)
            for start, end in _line_spans(files[0], workers)
        ]
        with Pool(min(workers, len(spans))) as pool:
            return merge_stats(pool.map(_count_span, spans))
    file_specs = [(path, normalize, chosen) for path in files]
    with Pool(min(workers, len(files))) as pool:
        return merge_stats(pool.map(_count_file_spec, file_specs))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m opskit.logs",
        description="Rank access-log endpoints by HTTP 5xx count and error rate.",
    )
    parser.add_argument("paths", nargs="+", help="access log paths (.gz is streamed)")
    parser.add_argument("--top", type=int, default=5, help="how many endpoints to print (default: 5)")
    parser.add_argument(
        "--normalize",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="collapse numeric path segments to {id} (default: on)",
    )
    parser.add_argument("--rates", action="store_true", help="also rank by error rate")
    parser.add_argument(
        "--min-requests",
        type=int,
        default=50,
        help="hide endpoints below this volume when ranking rates (default: 50)",
    )
    parser.add_argument(
        "--minutes",
        type=int,
        default=None,
        help="only requests after the latest timestamp minus N minutes (in-process, regex)",
    )
    parser.add_argument(
        "--bucket-seconds",
        type=int,
        default=None,
        help="also bucket the selected requests into windows of this many seconds",
    )
    parser.add_argument("--workers", type=int, default=1, help="process-pool size (default: 1)")
    parser.add_argument(
        "--parser",
        choices=("regex", "split"),
        default="regex",
        help="regex (default) or the split fast path; windows require regex",
    )
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    return parser


def _scan_window(
    paths: Sequence[str],
    *,
    minutes: int,
    normalize: bool,
) -> EndpointStats:
    """Two streaming passes: find the latest timestamp, then count after the cutoff."""
    if minutes < 0:
        raise ValueError("minutes must be >= 0")
    latest: datetime | None = None
    for path in paths:
        for record in iter_records(read_lines(path)):
            moment = _as_utc(record.timestamp)
            if latest is None or moment > latest:
                latest = moment
    stats = EndpointStats(Counter(), Counter(), 0)
    if latest is None:
        for path in paths:
            for line in read_lines(path):
                if parse_line(line) is None:
                    stats.bad += 1
        return stats
    cutoff = latest - timedelta(minutes=minutes)
    for path in paths:
        for line in read_lines(path):
            parsed = parse_line(line)
            if parsed is None:
                stats.bad += 1
                continue
            if _as_utc(parsed.timestamp) <= cutoff:
                continue
            endpoint = _endpoint(parsed.path, normalize)
            stats.requests[endpoint] += 1
            if is_server_error(parsed.status):
                stats.errors[endpoint] += 1
    return stats


def _buckets_for(paths: Sequence[str], *, minutes: int | None, bucket_seconds: int) -> list[WindowBucket]:
    if bucket_seconds < 1:
        raise ValueError("bucket-seconds must be >= 1")
    window = timedelta(seconds=bucket_seconds)

    def records() -> Iterator[AccessRecord]:
        for path in paths:
            yield from iter_records(read_lines(path))

    if minutes is None:
        return bucket_by_time(records(), window)
    latest: datetime | None = None
    for record in records():
        moment = _as_utc(record.timestamp)
        if latest is None or moment > latest:
            latest = moment
    if latest is None:
        return []
    cutoff = latest - timedelta(minutes=minutes)
    return bucket_by_time(after_cutoff(records(), cutoff), window)


def _report_payload(
    stats: EndpointStats,
    ranking: list[tuple[str, int]],
    rates: list[ErrorRate] | None,
    buckets: list[WindowBucket] | None,
    *,
    normalize: bool,
    parser: str,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "bad_lines": stats.bad,
        "requests": stats.request_count,
        "normalize": normalize,
        "parser": parser,
        "top_errors": [{"endpoint": endpoint, "errors": count} for endpoint, count in ranking],
    }
    if rates is not None:
        payload["error_rates"] = [
            {
                "endpoint": row.endpoint,
                "errors": row.errors,
                "requests": row.requests,
                "rate": row.rate,
                "percent": row.percent,
            }
            for row in rates
        ]
    if buckets is not None:
        payload["buckets"] = [
            {
                "start": bucket.start.isoformat(),
                "errors": bucket.errors,
                "requests": bucket.requests,
                "rate": bucket.rate,
            }
            for bucket in buckets
        ]
    return payload


def _format_text(
    ranking: list[tuple[str, int]],
    stats: EndpointStats,
    rates: list[ErrorRate] | None,
    buckets: list[WindowBucket] | None,
    *,
    min_requests: int,
) -> str:
    lines = ["5xx endpoints"]
    if ranking:
        for endpoint, count in ranking:
            lines.append(f"  {count:6d}  {endpoint}")
    else:
        lines.append("  (none)")
    lines.append(f"bad_lines: {stats.bad}")
    lines.append(f"requests: {stats.request_count}")
    if rates is not None:
        lines.append(f"error rates (min_requests={min_requests})")
        if rates:
            for row in rates:
                lines.append(f"  {row.percent:>6}  {row.endpoint}  {row.errors}/{row.requests}")
        else:
            lines.append("  (none)")
    if buckets is not None:
        lines.append("buckets")
        for bucket in buckets:
            lines.append(
                f"  {bucket.start.isoformat()}  errors={bucket.errors}  requests={bucket.requests}"
            )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point. Prints a text report, or JSON with ``--json``. Exit 0, or 1 on error."""
    args = _parser().parse_args(list(argv) if argv is not None else None)
    try:
        if args.minutes is not None and args.parser == "split":
            raise ValueError("time windows need the regex parser (it keeps the timestamp)")
        if args.minutes is not None:
            stats = _scan_window(args.paths, minutes=args.minutes, normalize=args.normalize)
        else:
            stats = count_files(
                args.paths,
                normalize=args.normalize,
                parser=args.parser,
                workers=args.workers,
            )
        ranking = stats.top_errors(args.top)
        rates = stats.error_rates(args.top, args.min_requests) if args.rates else None
        buckets = (
            _buckets_for(args.paths, minutes=args.minutes, bucket_seconds=args.bucket_seconds)
            if args.bucket_seconds is not None
            else None
        )
    except (OSError, ValueError) as exc:
        print(f"opskit.logs: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(_report_payload(
            stats, ranking, rates, buckets, normalize=args.normalize, parser=args.parser,
        ), indent=2))
    else:
        print(_format_text(ranking, stats, rates, buckets, min_requests=args.min_requests), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
