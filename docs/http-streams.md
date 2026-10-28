# HTTP client and file streams

`opskit.http_api` is a small REST client. `opskit.streams` reads and writes large files one chunk, line, or JSON object at a time. Neither module talks to AWS.

## Streams

Generators are enough for a single pass. Context managers close the file if the caller stops early. A path is closed by the helper; a file object you opened stays open. Gzip wrappers flush without closing a buffer you passed in.

```python
from opskit.streams import (
    iter_chunks,
    iter_gzip_jsonl,
    iter_jsonl,
    iter_lines,
    open_jsonl,
    process_jsonl,
    write_gzip_lines,
    write_jsonl,
)

for chunk in iter_chunks("disk.img", chunk_size=1024 * 1024):
    upload_somewhere(chunk)

for line in iter_lines("app.log"):
    if "ERROR" in line:
        print(line)

write_jsonl("out.jsonl", ({"n": n} for n in range(1_000_000)))
process_jsonl("out.jsonl", handle_record)

with open_jsonl("out.jsonl") as reader:
    for record in reader:
        handle_record(record)

write_gzip_lines("archive.gz", (line for line in iter_lines("app.log")))
for record in iter_gzip_jsonl("events.jsonl.gz"):
    handle_record(record)
```

`iter_chunks` calls `read(chunk_size)` and never `read()`. `iter_lines` calls `readline()`. Blank JSON Lines are skipped. A bad JSON line raises `JsonlError` with `line_number` set to the physical line.

Matching helpers: `write_chunks`, `iter_gzip_chunks`, `write_gzip_chunks`, `iter_gzip_lines`, `write_gzip_jsonl`, plus `ChunkReader`, `ChunkWriter`, `LineReader`, `LineWriter`, `JsonlReader`, `JsonlWriter`, `GzipReader`, and `GzipWriter`. `open_binary`, `open_text`, `open_gzip`, and `open_jsonl` return those context managers (`rb`/`wb` for bytes, `rt`/`wt` for text).

## REST client

Retries use `opskit.retry.retry` (capped exponential backoff and full jitter). The session is an `opskit.http.TimeoutSession` with a mandatory timeout and no urllib3 status retry, so a 503 is not swallowed before our retry runs. GET, HEAD, OPTIONS, PUT, and DELETE retry. POST and PATCH do not, unless you pass them in `retry_methods`.

```python
from opskit.http_api import ApiClient, BearerAuth

auth = BearerAuth(token)
with ApiClient("https://api.example.com", auth=auth, attempts=5) as api:
    created = api.post_json("/v1/jobs", {"name": "cleanup"})
    auth.token = refreshed_token  # read again on the next call
    for item in api.paginate("/v1/jobs", items_key="items", cursor_key="next_cursor"):
        handle(item)
    api.download("/v1/jobs/export", "jobs.jsonl", chunk_size=64 * 1024)
    api.upload("/v1/jobs/bundle", "bundle.tar.gz", raw=True)
```

`BearerAuth.token` can be replaced between calls. `HeaderAuth` or a plain dict adds fixed headers. A `requests` `AuthBase` (for example `HTTPBasicAuth`) is passed through as request auth.

`get_json`, `put_json`, `patch_json`, and `delete_json` decode JSON. `204` and an empty body return `None`. Status 400 and above raise `ApiError` with `status_code`, `body`, and `response`. Connection failures and HTTP 408, 429, 500, 502, 503, and 504 are retried. Anything else is raised on the first attempt.

`paginate` yields items when `items_key` is set, otherwise whole JSON pages. The next page comes from a string at `next_key` (default `"next"`), then `cursor_key` sent back as `cursor_param` (default `"cursor"`), then a `Link: rel="next"` header. Pass `max_pages` when a cursor might never end. The same URL and query is not requested twice.

`download` writes a sibling `.partial` file and renames it into place. A failed attempt deletes the partial file before the retry. `iter_bytes` yields the body instead of writing it. `upload(..., raw=False)` sends multipart form data with POST. `upload(..., raw=True)` sends the file as the body with PUT, which is retried. Paths are reopened on each attempt; file objects are rewound when they support `seek`.
