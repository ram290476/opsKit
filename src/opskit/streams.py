"""Constant-memory readers and writers for large files.

Every helper yields or writes one chunk, line, or JSON object at a time.
Use the generator functions for one-shot work and the context managers when
the file must close even if the caller stops early.

Generators that open a path close it when iteration finishes or the generator
is closed. File objects passed in are left open; gzip wrappers are flushed
without closing that underlying buffer.
"""
from __future__ import annotations

import gzip
import io
import json
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Any, BinaryIO, TextIO

DEFAULT_CHUNK_SIZE = 64 * 1024


class StreamError(ValueError):
    """A stream could not be read or written."""


class JsonlError(StreamError):
    """One JSON Lines record was not valid JSON."""

    def __init__(self, message: str, line_number: int):
        super().__init__(f"line {line_number}: {message}")
        self.line_number = line_number


def _check_chunk_size(chunk_size: int) -> int:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    return chunk_size


def _is_fileobj(source: object) -> bool:
    return hasattr(source, "read") or hasattr(source, "write")


def _chunk_iter(handle: BinaryIO, chunk_size: int) -> Iterator[bytes]:
    while True:
        chunk = handle.read(chunk_size)
        if not chunk:
            return
        yield chunk


def _line_iter(handle: TextIO | BinaryIO, encoding: str = "utf-8", errors: str = "strict") -> Iterator[str]:
    while True:
        line = handle.readline()
        if line == "" or line == b"":
            return
        if isinstance(line, bytes):
            line = line.decode(encoding, errors)
        yield line.removesuffix("\n").removesuffix("\r")


def _jsonl_iter(handle: TextIO | BinaryIO, encoding: str = "utf-8", errors: str = "strict") -> Iterator[Any]:
    for line_number, line in enumerate(_line_iter(handle, encoding, errors), start=1):
        text = line.strip()
        if not text:
            continue
        try:
            yield json.loads(text)
        except json.JSONDecodeError as exc:
            raise JsonlError(str(exc), line_number) from exc


def _as_line(line: str) -> str:
    text = line if isinstance(line, str) else str(line)
    if text.endswith("\n"):
        return text
    return text + "\n"


def _json_line(record: Any) -> str:
    return json.dumps(record, ensure_ascii=False, default=str, separators=(",", ":")) + "\n"


class ChunkReader:
    """Iterate binary chunks. Always use it as a context manager."""

    def __init__(self, source: str | Path | BinaryIO, chunk_size: int = DEFAULT_CHUNK_SIZE):
        self.source = source
        self.chunk_size = _check_chunk_size(chunk_size)
        self._handle: BinaryIO | None = None
        self._owned = False
        self.closed = True

    def __enter__(self) -> ChunkReader:
        if _is_fileobj(self.source):
            self._handle = self.source  # type: ignore[assignment]
            self._owned = False
        else:
            self._handle = Path(self.source).open("rb")
            self._owned = True
        self.closed = False
        return self

    def __exit__(self, *exc: object) -> bool:
        self.close()
        return False

    def close(self) -> None:
        if self._owned and self._handle is not None:
            self._handle.close()
        self._handle = None
        self._owned = False
        self.closed = True

    def __iter__(self) -> Iterator[bytes]:
        if self._handle is None:
            raise RuntimeError("ChunkReader must be used as a context manager")
        return _chunk_iter(self._handle, self.chunk_size)


class ChunkWriter:
    """Write binary chunks. Always use it as a context manager."""

    def __init__(self, destination: str | Path | BinaryIO):
        self.destination = destination
        self.bytes_written = 0
        self._handle: BinaryIO | None = None
        self._owned = False
        self.closed = True

    def __enter__(self) -> ChunkWriter:
        if _is_fileobj(self.destination):
            self._handle = self.destination  # type: ignore[assignment]
            self._owned = False
        else:
            path = Path(self.destination)
            path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = path.open("wb")
            self._owned = True
        self.closed = False
        return self

    def __exit__(self, *exc: object) -> bool:
        self.close()
        return False

    def close(self) -> None:
        if self._owned and self._handle is not None:
            self._handle.close()
        self._handle = None
        self._owned = False
        self.closed = True

    def write(self, chunk: bytes) -> int:
        if self._handle is None:
            raise RuntimeError("ChunkWriter must be used as a context manager")
        self._handle.write(chunk)
        self.bytes_written += len(chunk)
        return len(chunk)


class LineReader:
    """Iterate text lines without trailing newline characters."""

    def __init__(self, source: str | Path | TextIO, encoding: str = "utf-8", errors: str = "strict"):
        self.source = source
        self.encoding = encoding
        self.errors = errors
        self._handle: TextIO | BinaryIO | None = None
        self._owned = False
        self.closed = True

    def __enter__(self) -> LineReader:
        if _is_fileobj(self.source):
            self._handle = self.source  # type: ignore[assignment]
            self._owned = False
        else:
            self._handle = Path(self.source).open("r", encoding=self.encoding, errors=self.errors)
            self._owned = True
        self.closed = False
        return self

    def __exit__(self, *exc: object) -> bool:
        self.close()
        return False

    def close(self) -> None:
        if self._owned and self._handle is not None:
            self._handle.close()
        self._handle = None
        self._owned = False
        self.closed = True

    def __iter__(self) -> Iterator[str]:
        if self._handle is None:
            raise RuntimeError("LineReader must be used as a context manager")
        return _line_iter(self._handle, self.encoding, self.errors)


class LineWriter:
    """Write text lines, adding a newline when the line does not have one."""

    def __init__(self, destination: str | Path | TextIO, encoding: str = "utf-8"):
        self.destination = destination
        self.encoding = encoding
        self.lines_written = 0
        self._handle: TextIO | None = None
        self._owned = False
        self.closed = True

    def __enter__(self) -> LineWriter:
        if _is_fileobj(self.destination):
            self._handle = self.destination  # type: ignore[assignment]
            self._owned = False
        else:
            path = Path(self.destination)
            path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = path.open("w", encoding=self.encoding, newline="\n")
            self._owned = True
        self.closed = False
        return self

    def __exit__(self, *exc: object) -> bool:
        self.close()
        return False

    def close(self) -> None:
        if self._owned and self._handle is not None:
            self._handle.close()
        self._handle = None
        self._owned = False
        self.closed = True

    def write(self, line: str) -> None:
        if self._handle is None:
            raise RuntimeError("LineWriter must be used as a context manager")
        self._handle.write(_as_line(line))
        self.lines_written += 1


class JsonlReader:
    """Iterate JSON values, one per non-blank line."""

    def __init__(self, source: str | Path | TextIO, encoding: str = "utf-8", errors: str = "strict"):
        self.source = source
        self.encoding = encoding
        self.errors = errors
        self._handle: TextIO | BinaryIO | None = None
        self._owned = False
        self.closed = True

    def __enter__(self) -> JsonlReader:
        if _is_fileobj(self.source):
            self._handle = self.source  # type: ignore[assignment]
            self._owned = False
        else:
            self._handle = Path(self.source).open("r", encoding=self.encoding, errors=self.errors)
            self._owned = True
        self.closed = False
        return self

    def __exit__(self, *exc: object) -> bool:
        self.close()
        return False

    def close(self) -> None:
        if self._owned and self._handle is not None:
            self._handle.close()
        self._handle = None
        self._owned = False
        self.closed = True

    def __iter__(self) -> Iterator[Any]:
        if self._handle is None:
            raise RuntimeError("JsonlReader must be used as a context manager")
        return _jsonl_iter(self._handle, self.encoding, self.errors)


class JsonlWriter:
    """Write one JSON object per line."""

    def __init__(self, destination: str | Path | TextIO, encoding: str = "utf-8"):
        self.destination = destination
        self.encoding = encoding
        self.records_written = 0
        self._handle: TextIO | None = None
        self._owned = False
        self.closed = True

    def __enter__(self) -> JsonlWriter:
        if _is_fileobj(self.destination):
            self._handle = self.destination  # type: ignore[assignment]
            self._owned = False
        else:
            path = Path(self.destination)
            path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = path.open("w", encoding=self.encoding, newline="\n")
            self._owned = True
        self.closed = False
        return self

    def __exit__(self, *exc: object) -> bool:
        self.close()
        return False

    def close(self) -> None:
        if self._owned and self._handle is not None:
            self._handle.close()
        self._handle = None
        self._owned = False
        self.closed = True

    def write(self, record: Any) -> None:
        if self._handle is None:
            raise RuntimeError("JsonlWriter must be used as a context manager")
        self._handle.write(_json_line(record))
        self.records_written += 1


def _gzip_handle(source: str | Path | BinaryIO, mode: str, encoding: str):
    """Open a gzip wrapper. Closing it flushes gzip without closing a caller-owned buffer."""
    reading = "r" in mode
    binary_mode = "rb" if reading else "wb"
    text = "t" in mode
    if _is_fileobj(source):
        gz = gzip.GzipFile(fileobj=source, mode=binary_mode)  # type: ignore[arg-type]
        if not text:
            return gz
        return io.TextIOWrapper(gz, encoding=encoding, newline=None if reading else "\n")
    path = Path(source)
    if not reading:
        path.parent.mkdir(parents=True, exist_ok=True)
    if text:
        text_mode = "rt" if reading else "wt"
        newline = None if reading else "\n"
        return gzip.open(path, text_mode, encoding=encoding, newline=newline)
    return gzip.open(path, binary_mode)


class GzipReader:
    """Stream a gzip file as binary chunks, text lines, or JSON Lines.

    ``kind`` is ``binary``, ``text``, or ``jsonl``. Decompression is incremental,
    so memory stays proportional to ``chunk_size`` or one line.
    """

    def __init__(
        self,
        source: str | Path | BinaryIO,
        kind: str = "text",
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        encoding: str = "utf-8",
        errors: str = "strict",
    ):
        if kind not in {"binary", "text", "jsonl"}:
            raise ValueError("kind must be binary, text, or jsonl")
        self.source = source
        self.kind = kind
        self.chunk_size = _check_chunk_size(chunk_size)
        self.encoding = encoding
        self.errors = errors
        self._handle: Any = None
        self.closed = True

    def __enter__(self) -> GzipReader:
        mode = "rb" if self.kind == "binary" else "rt"
        self._handle = _gzip_handle(self.source, mode, self.encoding)
        self.closed = False
        return self

    def __exit__(self, *exc: object) -> bool:
        self.close()
        return False

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
        self._handle = None
        self.closed = True

    def __iter__(self) -> Iterator[Any]:
        if self._handle is None:
            raise RuntimeError("GzipReader must be used as a context manager")
        if self.kind == "binary":
            return _chunk_iter(self._handle, self.chunk_size)
        if self.kind == "text":
            return _line_iter(self._handle, self.encoding, self.errors)
        return _jsonl_iter(self._handle, self.encoding, self.errors)


class GzipWriter:
    """Write a gzip file as binary chunks, text lines, or JSON Lines."""

    def __init__(self, destination: str | Path | BinaryIO, kind: str = "text", encoding: str = "utf-8"):
        if kind not in {"binary", "text", "jsonl"}:
            raise ValueError("kind must be binary, text, or jsonl")
        self.destination = destination
        self.kind = kind
        self.encoding = encoding
        self.written = 0
        self._handle: Any = None
        self.closed = True

    def __enter__(self) -> GzipWriter:
        mode = "wb" if self.kind == "binary" else "wt"
        self._handle = _gzip_handle(self.destination, mode, self.encoding)
        self.closed = False
        return self

    def __exit__(self, *exc: object) -> bool:
        self.close()
        return False

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
        self._handle = None
        self.closed = True

    def write(self, value: Any) -> None:
        if self._handle is None:
            raise RuntimeError("GzipWriter must be used as a context manager")
        if self.kind == "binary":
            if not isinstance(value, (bytes, bytearray)):
                raise TypeError("binary gzip writes require bytes")
            self._handle.write(value)
            self.written += len(value)
            return
        if self.kind == "text":
            self._handle.write(_as_line(value))
            self.written += 1
            return
        self._handle.write(_json_line(value))
        self.written += 1


def iter_chunks(source: str | Path | BinaryIO, chunk_size: int = DEFAULT_CHUNK_SIZE) -> Iterator[bytes]:
    """Yield binary chunks from a path or open binary file."""
    with ChunkReader(source, chunk_size) as reader:
        yield from reader


def write_chunks(destination: str | Path | BinaryIO, chunks: Iterable[bytes]) -> int:
    """Write binary chunks. Returns the number of bytes written."""
    with ChunkWriter(destination) as writer:
        for chunk in chunks:
            if chunk:
                writer.write(chunk)
        return writer.bytes_written


def iter_lines(
    source: str | Path | TextIO,
    encoding: str = "utf-8",
    errors: str = "strict",
) -> Iterator[str]:
    """Yield text lines without trailing newline characters."""
    with LineReader(source, encoding, errors) as reader:
        yield from reader


def write_lines(destination: str | Path | TextIO, lines: Iterable[str], encoding: str = "utf-8") -> int:
    """Write lines, adding a newline when one is missing. Returns the line count."""
    with LineWriter(destination, encoding) as writer:
        for line in lines:
            writer.write(line)
        return writer.lines_written


def iter_jsonl(
    source: str | Path | TextIO,
    encoding: str = "utf-8",
    errors: str = "strict",
) -> Iterator[Any]:
    """Yield one decoded JSON value per non-blank line."""
    with JsonlReader(source, encoding, errors) as reader:
        yield from reader


def write_jsonl(destination: str | Path | TextIO, records: Iterable[Any], encoding: str = "utf-8") -> int:
    """Write JSON Lines. Returns the record count."""
    with JsonlWriter(destination, encoding) as writer:
        for record in records:
            writer.write(record)
        return writer.records_written


def process_jsonl(
    source: str | Path | TextIO,
    fn: Callable[[Any], Any],
    encoding: str = "utf-8",
) -> int:
    """Call ``fn`` once per JSON Lines record. Returns the record count."""
    count = 0
    for record in iter_jsonl(source, encoding=encoding):
        fn(record)
        count += 1
    return count


def iter_gzip_chunks(
    source: str | Path | BinaryIO,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> Iterator[bytes]:
    """Yield decompressed binary chunks from a gzip stream."""
    with GzipReader(source, kind="binary", chunk_size=chunk_size) as reader:
        yield from reader


def iter_gzip_lines(
    source: str | Path | BinaryIO,
    encoding: str = "utf-8",
    errors: str = "strict",
) -> Iterator[str]:
    """Yield decompressed text lines from a gzip stream."""
    with GzipReader(source, kind="text", encoding=encoding, errors=errors) as reader:
        yield from reader


def iter_gzip_jsonl(
    source: str | Path | BinaryIO,
    encoding: str = "utf-8",
    errors: str = "strict",
) -> Iterator[Any]:
    """Yield JSON objects from a gzip-compressed JSON Lines stream."""
    with GzipReader(source, kind="jsonl", encoding=encoding, errors=errors) as reader:
        yield from reader


def write_gzip_chunks(destination: str | Path | BinaryIO, chunks: Iterable[bytes]) -> int:
    """Compress binary chunks. Returns the number of uncompressed bytes written."""
    with GzipWriter(destination, kind="binary") as writer:
        for chunk in chunks:
            if chunk:
                writer.write(chunk)
        return writer.written


def write_gzip_lines(
    destination: str | Path | BinaryIO,
    lines: Iterable[str],
    encoding: str = "utf-8",
) -> int:
    """Compress text lines. Returns the line count."""
    with GzipWriter(destination, kind="text", encoding=encoding) as writer:
        for line in lines:
            writer.write(line)
        return writer.written


def write_gzip_jsonl(
    destination: str | Path | BinaryIO,
    records: Iterable[Any],
    encoding: str = "utf-8",
) -> int:
    """Compress JSON Lines. Returns the record count."""
    with GzipWriter(destination, kind="jsonl", encoding=encoding) as writer:
        for record in records:
            writer.write(record)
        return writer.written


def open_binary(path: str | Path, mode: str = "rb", chunk_size: int = DEFAULT_CHUNK_SIZE):
    """Context manager yielding a ``ChunkReader`` (``rb``) or ``ChunkWriter`` (``wb``)."""
    if "r" in mode:
        return ChunkReader(path, chunk_size)
    if "w" in mode:
        return ChunkWriter(path)
    raise ValueError("mode must contain 'r' or 'w'")


def open_text(path: str | Path, mode: str = "rt", encoding: str = "utf-8"):
    """Context manager yielding a ``LineReader`` (``rt``) or ``LineWriter`` (``wt``)."""
    if "r" in mode:
        return LineReader(path, encoding)
    if "w" in mode:
        return LineWriter(path, encoding)
    raise ValueError("mode must contain 'r' or 'w'")


def open_gzip(
    path: str | Path | BinaryIO,
    mode: str = "rt",
    encoding: str = "utf-8",
    chunk_size: int = DEFAULT_CHUNK_SIZE,
):
    """Context manager yielding a ``GzipReader`` or ``GzipWriter``.

    ``rb`` / ``wb`` select binary chunks. ``rt`` / ``wt`` select text lines.
    """
    if "r" in mode:
        kind = "binary" if "b" in mode else "text"
        return GzipReader(path, kind=kind, encoding=encoding, chunk_size=chunk_size)
    if "w" in mode:
        kind = "binary" if "b" in mode else "text"
        return GzipWriter(path, kind=kind, encoding=encoding)
    raise ValueError("mode must contain 'r' or 'w'")


def open_jsonl(path: str | Path, mode: str = "rt", encoding: str = "utf-8"):
    """Context manager yielding a ``JsonlReader`` or ``JsonlWriter``."""
    if "r" in mode:
        return JsonlReader(path, encoding)
    if "w" in mode:
        return JsonlWriter(path, encoding)
    raise ValueError("mode must contain 'r' or 'w'")
