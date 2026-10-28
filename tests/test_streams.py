import io

import pytest

from opskit.streams import (
    DEFAULT_CHUNK_SIZE,
    ChunkReader,
    GzipReader,
    JsonlError,
    JsonlReader,
    LineReader,
    iter_chunks,
    iter_gzip_chunks,
    iter_gzip_jsonl,
    iter_gzip_lines,
    iter_jsonl,
    iter_lines,
    open_binary,
    open_gzip,
    open_jsonl,
    open_text,
    process_jsonl,
    write_chunks,
    write_gzip_chunks,
    write_gzip_jsonl,
    write_gzip_lines,
    write_jsonl,
    write_lines,
)


class TrackingBinary(io.BytesIO):
    def __init__(self, data: bytes):
        super().__init__(data)
        self.sizes: list[int] = []

    def read(self, size: int = -1) -> bytes:
        self.sizes.append(size)
        return super().read(size)


class TrackingText:
    """Only readline() is valid. read() would pull the whole buffer."""

    def __init__(self, lines: list[str]):
        self._lines = list(lines)
        self.readline_sizes: list[int] = []

    def readline(self, size: int = -1) -> str:
        self.readline_sizes.append(size)
        if not self._lines:
            return ""
        return self._lines.pop(0)

    def read(self, size: int = -1) -> str:
        raise AssertionError("read() would load the whole file")


def test_binary_chunks_are_bounded_and_round_trip(tmp_path):
    payload = b"abcdefghij" * 1000
    path = tmp_path / "blob.bin"
    assert write_chunks(path, (payload[i:i + 64] for i in range(0, len(payload), 64))) == len(payload)
    chunks = list(iter_chunks(path, chunk_size=100))
    assert b"".join(chunks) == payload
    assert all(len(chunk) <= 100 for chunk in chunks)
    assert chunks[0] != payload


def test_chunk_reader_requests_fixed_sizes_from_file_object():
    tracker = TrackingBinary(b"x" * 250)
    chunks = list(iter_chunks(tracker, chunk_size=100))
    assert b"".join(chunks) == b"x" * 250
    assert tracker.sizes
    assert all(size == 100 for size in tracker.sizes)


def test_lines_use_readline_and_round_trip(tmp_path):
    tracker = TrackingText(["alpha\n", "beta\r\n", "gamma"])
    assert list(iter_lines(tracker)) == ["alpha", "beta", "gamma"]
    assert tracker.readline_sizes

    path = tmp_path / "nested" / "lines.txt"

    def lines():
        for i in range(1000):
            yield f"row-{i}-café"

    assert write_lines(path, lines()) == 1000
    assert sum(1 for _ in iter_lines(path)) == 1000
    assert next(iter_lines(path)) == "row-0-café"


def test_jsonl_round_trip_skips_blanks_and_reports_line_number(tmp_path):
    path = tmp_path / "events.jsonl"
    records = [{"n": 1, "text": "a"}, {"n": 2}]
    assert write_jsonl(path, (record for record in records)) == 2
    assert list(iter_jsonl(path)) == records

    seen: list[int] = []
    assert process_jsonl(path, lambda record: seen.append(record["n"])) == 2
    assert seen == [1, 2]

    broken = tmp_path / "broken.jsonl"
    broken.write_text('\n{bad\n', encoding="utf-8")
    with pytest.raises(JsonlError) as exc:
        list(iter_jsonl(broken))
    assert exc.value.line_number == 2


def test_gzip_binary_text_and_jsonl_round_trip(tmp_path):
    raw = b"0123456789" * 300
    binary_path = tmp_path / "blob.gz"
    assert write_gzip_chunks(binary_path, (raw[i:i + 50] for i in range(0, len(raw), 50))) == len(raw)
    restored = b"".join(iter_gzip_chunks(binary_path, chunk_size=64))
    assert restored == raw
    assert all(len(chunk) <= 64 for chunk in iter_gzip_chunks(binary_path, chunk_size=64))

    buffer = io.BytesIO()
    assert write_gzip_lines(buffer, (f"line-{i}" for i in range(3))) == 3
    buffer.seek(0)
    assert list(iter_gzip_lines(buffer)) == ["line-0", "line-1", "line-2"]
    assert not buffer.closed

    jsonl_path = tmp_path / "records.jsonl.gz"
    payload = [{"ok": True}, {"n": 2}]
    assert write_gzip_jsonl(jsonl_path, payload) == 2
    assert list(iter_gzip_jsonl(jsonl_path)) == payload


def test_context_managers_close_on_success_and_error(tmp_path):
    path = tmp_path / "data.bin"
    with open_binary(path, "wb") as writer:
        writer.write(b"abc")
    assert writer.closed
    with open_binary(path, "rb", chunk_size=2) as reader:
        assert list(reader) == [b"ab", b"c"]
    assert reader.closed

    text = tmp_path / "notes.txt"
    with open_text(text, "wt") as writer:
        writer.write("one")
    with open_text(text, "rt") as reader:
        assert list(reader) == ["one"]

    jsonl = tmp_path / "rows.jsonl"
    with open_jsonl(jsonl, "wt") as writer:
        writer.write({"a": 1})
    with open_jsonl(jsonl, "rt") as reader:
        assert list(reader) == [{"a": 1}]

    gz = tmp_path / "notes.gz"
    with open_gzip(gz, "wt") as writer:
        writer.write("zipped")
    with open_gzip(gz, "rt") as reader:
        assert list(reader) == ["zipped"]

    with pytest.raises(RuntimeError):
        with LineReader(text) as reader:
            raise RuntimeError("boom")
    assert reader.closed
    with pytest.raises(RuntimeError):
        with JsonlReader(jsonl) as reader:
            raise RuntimeError("boom")
    assert reader.closed
    with pytest.raises(RuntimeError):
        with GzipReader(gz, kind="text") as reader:
            raise RuntimeError("boom")
    assert reader.closed
    with pytest.raises(RuntimeError):
        with ChunkReader(path) as reader:
            raise RuntimeError("boom")
    assert reader.closed


def test_readers_require_context_and_reject_bad_arguments(tmp_path):
    path = tmp_path / "empty.bin"
    path.write_bytes(b"")
    reader = ChunkReader(path)
    with pytest.raises(RuntimeError):
        iter(reader)
    with pytest.raises(ValueError):
        list(iter_chunks(path, chunk_size=0))
    with pytest.raises(ValueError):
        GzipReader(path, kind="nope")
    assert DEFAULT_CHUNK_SIZE > 0
