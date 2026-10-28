"""Sample access logs and the explainer's published results.

The 2,000-line fixture is the scenario from "Find the Top Error Endpoints":
checkout has 12 errors in 98 requests (12.2%), each ``/api/orders/<id>`` shows
up once until normalization makes orders the top endpoint with 20 errors, and
the last 10 minutes of the hour keep 333 requests.
"""
import gzip
import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone

import pytest

from opskit.logs import (
    ACCESS_LOG_RE,
    after_cutoff,
    bucket_by_time,
    count_files,
    error_rates,
    is_server_error,
    iter_records,
    main,
    merge_counters,
    normalize_endpoint,
    open_log,
    parse_line,
    parse_named,
    parse_split,
    read_lines,
    recent,
    scan_lines,
    top_error_endpoints,
)

START = datetime(2026, 10, 27, 12, 0, 0, tzinfo=timezone.utc)
SAMPLE = (
    '10.0.1.5 - - [27/Oct/2026:12:00:00 +0000] "GET /login HTTP/1.1" 500 512'
)
BROKEN = [
    "this is not a log line",
    "",
    '10.0.0.1 - - [27/Oct/2026:12:00:00 +0000] "GET /login HTTP/1.1" xyz 10',
]


def access_line(moment, method, path, status, size=512, ip="10.0.1.5"):
    stamp = moment.strftime("%d/%b/%Y:%H:%M:%S %z")
    return f'{ip} - - [{stamp}] "{method} {path} HTTP/1.1" {status} {size}'


def _timestamp(index: int) -> datetime:
    """Place 1,667 requests at or before the 50-minute mark and 333 after it."""
    early = 1667
    if index < early:
        offset = round(index * 3000 / (early - 1))
        return START + timedelta(seconds=offset)
    late = 2000 - early
    offset = 3001 + round((index - early) * (3600 - 3001) / (late - 1))
    return START + timedelta(seconds=offset)


def sample_lines() -> list[str]:
    """2,000 valid Common Log lines plus a few broken ones."""
    rows: list[tuple[str, str, str]] = []
    rows += [("/checkout", "500", "POST")] * 11
    rows += [("/checkout", "503", "POST")]
    rows += [("/checkout", "404", "POST")] * 10
    rows += [("/checkout", "200", "POST")] * 76
    for ident in range(1001, 1021):
        rows.append((f"/api/orders/{ident}", "500", "GET"))
    rows += [("/login", "500", "POST")] * 5
    rows += [("/login", "503", "POST")]
    rows += [("/login", "200", "POST")] * 144
    rows += [("/search?q=red", "500", "GET")] * 2
    rows += [("/search", "502", "GET")] * 2
    rows += [("/search?q=blue", "200", "GET")] * 50
    rows += [("/search", "200", "GET")] * 346
    rows += [("/api/health", "200", "GET")] * 500
    rows += [("/static/app.js", "200", "GET")] * 832
    assert len(rows) == 2000
    lines = [
        access_line(_timestamp(index), method, path, status)
        for index, (path, status, method) in enumerate(rows)
    ]
    return lines + BROKEN


def _write(path, lines, *, newline=True):
    text = "\n".join(lines)
    if newline:
        text += "\n"
    path.write_text(text, encoding="utf-8")


def test_fields_by_position_and_named_groups():
    fields = SAMPLE.split()
    assert fields[3] == "[27/Oct/2026:12:00:00"
    assert fields[4] == "+0000]"
    assert len(fields) >= 10
    assert fields[6] == "/login"
    assert fields[8] == "500"

    assert parse_split(SAMPLE) == ("/login", "500")
    assert parse_named(SAMPLE) == {
        "ip": "10.0.1.5",
        "ident": "-",
        "user": "-",
        "time": "27/Oct/2026:12:00:00 +0000",
        "method": "GET",
        "path": "/login",
        "protocol": "HTTP/1.1",
        "status": "500",
        "size": "512",
    }
    record = parse_line(SAMPLE)
    assert record is not None
    assert record.timestamp == START
    assert record.status == "500"
    assert isinstance(ACCESS_LOG_RE, re.Pattern)


def test_both_parsers_return_none_for_garbage_and_keep_going():
    for line in BROKEN:
        assert parse_named(line) is None
        assert parse_split(line) is None
        assert parse_line(line) is None
    lines = [SAMPLE, *BROKEN, SAMPLE.replace("500", "200")]
    ranking, bad = top_error_endpoints(lines, n=5)
    assert bad == len(BROKEN)
    assert ranking == [("/login", 1)]


def test_split_accepts_combined_log_extra_fields_and_dash_size():
    combined = SAMPLE + ' "-" "Mozilla/5.0 (compatible)"'
    assert parse_split(combined) == ("/login", "500")
    assert parse_named(combined)["path"] == "/login"
    dashed = SAMPLE.replace("512", "-").replace("500", "200")
    assert parse_split(dashed) == ("/login", "200")
    assert parse_named(dashed)["size"] == "-"


def test_server_error_is_5xx_prefix_not_4xx():
    assert is_server_error("500")
    assert is_server_error("503")
    assert is_server_error(502)
    assert not is_server_error("404")
    assert not is_server_error("200")
    assert not is_server_error("302")


def test_normalize_drops_query_and_replaces_digit_segments():
    assert normalize_endpoint("/api/users/123") == "/api/users/{id}"
    assert normalize_endpoint("/api/orders/17?x=1") == "/api/orders/{id}"
    assert normalize_endpoint("/search?q=red") == "/search"
    assert normalize_endpoint("/checkout") == "/checkout"
    assert normalize_endpoint("/a/1/b/2") == "/a/{id}/b/{id}"


def test_raw_ranking_checkout_has_twelve_and_each_order_is_once():
    stats = scan_lines(sample_lines())
    ranking, bad = top_error_endpoints(sample_lines(), n=5)
    orders = [path for path in stats.errors if path.startswith("/api/orders/")]
    assert bad == len(BROKEN)
    assert ranking[0] == ("/checkout", 12)
    assert len(orders) == 20
    assert all(stats.errors[path] == 1 for path in orders)
    assert stats.requests["/checkout"] == 98
    assert stats.errors["/checkout"] == 12


def test_normalized_orders_has_twenty_and_tops_the_list():
    ranking, bad = top_error_endpoints(sample_lines(), n=5, normalize=True)
    assert bad == len(BROKEN)
    assert ranking[0] == ("/api/orders/{id}", 20)
    assert ranking[1] == ("/checkout", 12)
    # The split fast path sees the same paths and statuses on this fixture.
    fast, fast_bad = top_error_endpoints(sample_lines(), n=2, normalize=True, parser="split")
    assert fast_bad == bad
    assert fast == ranking[:2]


def test_checkout_error_rate_is_12_point_2_percent():
    rates = error_rates(sample_lines(), n=5, min_requests=50)
    checkout = rates[0]
    assert checkout.endpoint == "/checkout"
    assert checkout.errors == 12
    assert checkout.requests == 98
    assert checkout.percent == "12.2%"
    assert checkout.rate == pytest.approx(12 / 98)
    assert [row.endpoint for row in rates] == [
        "/checkout",
        "/login",
        "/search",
        "/api/health",
        "/static/app.js",
    ]
    assert rates[1].percent == "4.0%"
    assert all(row.endpoint != "/api/orders/{id}" for row in rates)


def test_minimum_hides_a_single_failure_that_would_be_100_percent():
    lines = [
        access_line(START, "GET", "/once", "500"),
        access_line(START, "GET", "/ok", "200"),
    ]
    assert error_rates(lines, min_requests=1)[0].percent == "100.0%"
    assert error_rates(lines, min_requests=50) == []


def test_last_ten_minutes_keeps_333_requests():
    records = list(iter_records(sample_lines()))
    assert len(records) == 2000
    end = START + timedelta(hours=1)
    assert len(list(recent(records, minutes=10, now=end))) == 333
    assert len(list(recent(records, minutes=10))) == 333
    cutoff = end - timedelta(minutes=10)
    assert len(list(after_cutoff(records, cutoff))) == 333
    assert records[1666].timestamp == cutoff
    assert records[1667].timestamp > cutoff


def test_time_buckets_cover_every_request_and_every_5xx():
    records = list(iter_records(sample_lines()))
    buckets = bucket_by_time(records, timedelta(minutes=1))
    assert buckets
    assert [bucket.start for bucket in buckets] == sorted(bucket.start for bucket in buckets)
    assert sum(bucket.requests for bucket in buckets) == 2000
    assert sum(bucket.errors for bucket in buckets) == 42
    assert buckets[0].rate == pytest.approx(buckets[0].errors / buckets[0].requests)
    with pytest.raises(ValueError):
        bucket_by_time(records, timedelta(0))


def test_gzip_stream_matches_the_plain_file(tmp_path):
    lines = sample_lines()
    plain = tmp_path / "access.log"
    compressed = tmp_path / "access.log.gz"
    _write(plain, lines)
    with gzip.open(compressed, "wt", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")

    with open_log(compressed) as handle:
        assert isinstance(handle.buffer, gzip.GzipFile)
    plain_top = top_error_endpoints(read_lines(plain), n=5, normalize=True)
    gzip_top = top_error_endpoints(read_lines(compressed), n=5, normalize=True)
    assert gzip_top == plain_top
    assert gzip_top.ranking[0] == ("/api/orders/{id}", 20)

    streamed = read_lines(plain)
    assert next(streamed).startswith("10.0.1.5 ")


def test_four_files_merge_to_one_result(tmp_path):
    lines = sample_lines()
    paths = []
    for index in range(4):
        path = tmp_path / f"part-{index}.log"
        _write(path, lines[index::4])
        paths.append(path)
    merged = count_files(paths, normalize=True, workers=4)
    single = scan_lines(lines, normalize=True)
    assert merged.errors == single.errors
    assert merged.requests == single.requests
    assert merged.bad == single.bad
    assert merged.top_errors(1) == [("/api/orders/{id}", 20)]
    assert merged.request_count + merged.bad == len(lines)


def test_parallel_chunks_of_one_file_match_the_stream(tmp_path):
    lines = sample_lines()
    path = tmp_path / "access.log"
    _write(path, lines, newline=False)
    parallel = count_files([path], normalize=True, workers=4)
    streamed = count_files([path], normalize=True, workers=1)
    assert parallel.errors == streamed.errors
    assert parallel.requests == streamed.requests
    assert parallel.bad == streamed.bad
    assert parallel.request_count + parallel.bad == len(lines)

    tiny = tmp_path / "tiny.log"
    tiny_lines = [
        access_line(START, "GET", "/a", "500"),
        "garbage",
        access_line(START, "GET", "/a", "200"),
    ]
    _write(tiny, tiny_lines, newline=False)
    stats = count_files([tiny], workers=8, parser="split")
    assert stats.request_count + stats.bad == len(tiny_lines)
    assert stats.errors["/a"] == 1


def test_gzip_with_extra_workers_stays_a_single_stream(tmp_path):
    lines = sample_lines()
    path = tmp_path / "access.log.gz"
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    assert count_files([path], normalize=True, workers=4).errors == scan_lines(lines, normalize=True).errors


def test_merge_counters_uses_addition():
    assert merge_counters([Counter(a=1), Counter(a=2, b=1), Counter()]) == Counter(a=3, b=1)
    assert merge_counters([]) == Counter()


def test_bad_input_and_empty_do_not_raise():
    ranking, bad = top_error_endpoints(["", "nope", "still bad"])
    assert ranking == []
    assert bad == 3
    assert top_error_endpoints([]).ranking == []
    assert list(recent([], minutes=10)) == []
    with pytest.raises(ValueError):
        top_error_endpoints([SAMPLE], n=0)
    with pytest.raises(ValueError):
        error_rates([SAMPLE], min_requests=0)
    with pytest.raises(ValueError):
        scan_lines([SAMPLE], parser="xml")


def test_cli_json_reports_the_explainer_numbers(tmp_path, capsys):
    path = tmp_path / "access.log"
    _write(path, sample_lines())
    assert main([
        str(path),
        "--json",
        "--top", "2",
        "--rates",
        "--min-requests", "50",
        "--minutes", "10",
        "--bucket-seconds", "60",
    ]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["requests"] == 333
    assert payload["bad_lines"] == len(BROKEN)
    assert payload["normalize"] is True
    assert payload["buckets"]
    assert sum(bucket["requests"] for bucket in payload["buckets"]) == 333

    assert main([str(path), "--json", "--top", "2", "--no-normalize", "--workers", "2"]) == 0
    full = json.loads(capsys.readouterr().out)
    assert full["requests"] == 2000
    assert full["top_errors"][0] == {"endpoint": "/checkout", "errors": 12}

    assert main([str(path), "--rates", "--min-requests", "50", "--parser", "split"]) == 0
    text = capsys.readouterr().out
    assert "12.2%" in text
    assert "/checkout  12/98" in text
    assert "/api/orders/{id}" in text


def test_cli_missing_file_and_split_window_exit_1(tmp_path, capsys):
    missing = tmp_path / "missing.log"
    assert main([str(missing)]) == 1
    assert "opskit.logs:" in capsys.readouterr().err
    present = tmp_path / "access.log"
    _write(present, [SAMPLE])
    assert main([str(present), "--minutes", "5", "--parser", "split"]) == 1
    assert "regex" in capsys.readouterr().err
