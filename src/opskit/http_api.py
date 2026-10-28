"""Reusable REST client with timeouts, auth, pagination, and streamed bodies.

Retries go through :func:`opskit.retry.retry` (capped exponential backoff with
full jitter). The session is a :class:`opskit.http.TimeoutSession` without
urllib3's status retry, so a 503 is raised once and then retried here.
POST and PATCH are not retried unless they are listed in ``retry_methods``;
GET, HEAD, OPTIONS, PUT, and DELETE are.

Downloads and uploads read or write one chunk at a time. A download is written
to a sibling ``.partial`` file and renamed into place after the body succeeds.
"""
from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
from requests.auth import AuthBase

from .http import TimeoutSession
from .retry import is_transient, retry
from .streams import DEFAULT_CHUNK_SIZE

IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})


class ApiError(RuntimeError):
    """An HTTP response was not successful, or its body was not usable JSON."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        body: Any = None,
        response: Any = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.body = body
        self.response = response


class BearerAuth:
    """``Authorization: Bearer`` header. Assign ``token`` to rotate it."""

    def __init__(self, token: str):
        self.token = token

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


class HeaderAuth:
    """Send a fixed set of headers, such as an API key, on every request."""

    def __init__(self, headers: Mapping[str, str]):
        self._headers = dict(headers)

    def headers(self) -> dict[str, str]:
        return dict(self._headers)


def _retryable_http(exc: BaseException) -> bool:
    """Transient AWS/HTTP statuses plus requests transport failures."""
    if is_transient(exc):
        return True
    return isinstance(
        exc,
        (requests.ConnectionError, requests.Timeout, requests.exceptions.ChunkedEncodingError),
    )


def _error_from(response: requests.Response) -> ApiError:
    try:
        body: Any = response.json()
    except ValueError:
        text = response.text or ""
        body = text[:2000]
    message = f"HTTP {response.status_code} for {response.request.method} {response.url}"
    return ApiError(message, status_code=response.status_code, body=body, response=response)


def _interpret(response: requests.Response) -> Any:
    if response.status_code == 204 or not response.content:
        return None
    content_type = response.headers.get("Content-Type", "")
    if "json" in content_type.lower() or response.text[:1] in "[{":
        try:
            return response.json()
        except ValueError as exc:
            raise ApiError(
                "response was not JSON",
                status_code=response.status_code,
                body=response.text[:2000],
                response=response,
            ) from exc
    return response.text


def _items(payload: Any, items_key: str | None) -> list[Any]:
    if items_key is None:
        return []
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        value = payload.get(items_key, [])
        if isinstance(value, list):
            return value
    return []


def _next_request(
    url: str,
    params: dict[str, Any],
    response: requests.Response,
    payload: Any,
    next_key: str,
    cursor_key: str | None,
    cursor_param: str,
) -> tuple[str, dict[str, Any]] | None:
    if isinstance(payload, dict):
        nxt = payload.get(next_key)
        if isinstance(nxt, str) and nxt:
            return urljoin(url, nxt), {}
        if cursor_key is not None and cursor_key in payload:
            cursor = payload.get(cursor_key)
            if cursor is not None and cursor != "":
                updated = dict(params)
                updated[cursor_param] = cursor
                return url, updated
    link = (getattr(response, "links", None) or {}).get("next", {}).get("url")
    if link:
        return link, {}
    return None


class _BorrowedFile:
    def __init__(self, source: str | Path | Any):
        self.source = source
        self._owned = False
        self.handle: Any = None
        self.name = "upload"

    def __enter__(self) -> tuple[Any, str]:
        if isinstance(self.source, (str, Path)):
            path = Path(self.source)
            self.handle = path.open("rb")
            self._owned = True
            self.name = path.name
        else:
            self.handle = self.source
            raw_name = getattr(self.source, "name", "")
            self.name = Path(raw_name).name if isinstance(raw_name, str) and raw_name else "upload"
        return self.handle, self.name

    def __exit__(self, *exc: object) -> bool:
        if self._owned and self.handle is not None:
            self.handle.close()
        return False


class ApiClient:
    """Call a REST API with a shared session, timeouts, and bounded retries.

    ``base_url`` is prefixed onto relative paths. Absolute URLs are used as
    given, which is how pagination follows a ``next`` link on another host.

    Dry-run does not apply here: every call is sent. Destructive cloud changes
    belong in the AWS helpers, which use :class:`opskit.safety.ChangeBudget`.
    """

    def __init__(
        self,
        base_url: str = "",
        *,
        timeout: float | tuple[float, float] = (3.05, 30),
        headers: Mapping[str, str] | None = None,
        auth: Any = None,
        attempts: int = 5,
        retry_base: float = 0.5,
        retry_cap: float = 30.0,
        retry_methods: Iterable[str] = IDEMPOTENT_METHODS,
        session: requests.Session | None = None,
        sleep: Any = None,
        user_agent: str = "opskit/1.0",
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.headers = dict(headers or {})
        self.attempts = attempts
        self.retry_base = retry_base
        self.retry_cap = retry_cap
        self.retry_methods = frozenset(method.upper() for method in retry_methods)
        self._sleep = sleep
        self._owns_session = session is None
        if session is None:
            # No urllib3 status retry: opskit.retry is the only backoff.
            self.session = TimeoutSession(timeout)
            self.session.headers["User-Agent"] = user_agent
        else:
            self.session = session
        self._requests_auth: AuthBase | None = None
        self._header_auth: Any = None
        self._set_auth(auth)

    def _set_auth(self, auth: Any) -> None:
        self._requests_auth = None
        self._header_auth = None
        if auth is None:
            return
        if isinstance(auth, Mapping):
            self._header_auth = HeaderAuth(auth)
            return
        if isinstance(auth, AuthBase):
            self._requests_auth = auth
            return
        if callable(getattr(auth, "headers", None)):
            self._header_auth = auth
            return
        raise TypeError("auth must be a mapping, requests AuthBase, or an object with headers()")

    def _headers(self, extra: Mapping[str, str] | None) -> dict[str, str]:
        merged = dict(self.headers)
        if self._header_auth is not None:
            merged.update(self._header_auth.headers())
        if extra:
            merged.update(extra)
        return merged

    def _url(self, path: str) -> str:
        if path.startswith(("http://", "https://")):
            return path
        if not self.base_url:
            return path
        return urljoin(self.base_url + "/", path.lstrip("/"))

    def _send(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        data: Any = None,
        headers: Mapping[str, str] | None = None,
        files: Any = None,
        stream: bool = False,
        timeout: float | tuple[float, float] | None = None,
    ) -> requests.Response:
        kwargs: dict[str, Any] = {
            "params": params,
            "headers": headers,
            "stream": stream,
            "timeout": self.timeout if timeout is None else timeout,
        }
        if json is not None:
            kwargs["json"] = json
        if data is not None:
            kwargs["data"] = data
        if files is not None:
            kwargs["files"] = files
        if self._requests_auth is not None:
            kwargs["auth"] = self._requests_auth
        response = self.session.request(method, url, **kwargs)
        if response.status_code >= 400:
            raise _error_from(response)
        return response

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        data: Any = None,
        headers: Mapping[str, str] | None = None,
        files: Any = None,
        stream: bool = False,
        timeout: float | tuple[float, float] | None = None,
        retry_methods: Iterable[str] | None = None,
    ) -> requests.Response:
        """Send one HTTP request and return the response after a success status.

        Failures become :class:`ApiError`. Transient failures are retried when
        ``method`` is in ``retry_methods``.
        """
        verb = method.upper()
        allowed = self.retry_methods if retry_methods is None else frozenset(m.upper() for m in retry_methods)
        attempts = self.attempts if verb in allowed else 1
        url = self._url(path)
        sleep = self._sleep

        def _do() -> requests.Response:
            return self._send(
                verb,
                url,
                params=params,
                json=json,
                data=data,
                headers=self._headers(headers),
                files=files,
                stream=stream,
                timeout=timeout,
            )

        if attempts <= 1:
            return _do()
        decorated = retry(
            attempts=attempts,
            base=self.retry_base,
            cap=self.retry_cap,
            when=_retryable_http,
            **({"sleep": sleep} if sleep is not None else {}),
        )(_do)
        return decorated()

    def _json(
        self,
        method: str,
        path: str,
        *,
        body: Any = None,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        extra = {"Accept": "application/json"}
        if headers:
            extra.update(headers)
        response = self.request(method, path, params=params, json=body, headers=extra)
        return _interpret(response)

    def get_json(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        """GET a JSON body. ``204`` and empty bodies return ``None``."""
        return self._json("GET", path, params=params, headers=headers)

    def post_json(
        self,
        path: str,
        body: Any,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        """POST a JSON body. Not retried unless POST is in ``retry_methods``."""
        return self._json("POST", path, body=body, params=params, headers=headers)

    def put_json(
        self,
        path: str,
        body: Any,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        """PUT a JSON body."""
        return self._json("PUT", path, body=body, params=params, headers=headers)

    def patch_json(
        self,
        path: str,
        body: Any,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        """PATCH a JSON body. Not retried unless PATCH is in ``retry_methods``."""
        return self._json("PATCH", path, body=body, params=params, headers=headers)

    def delete_json(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        """DELETE and decode a JSON body when one is present."""
        return self._json("DELETE", path, params=params, headers=headers)

    def paginate(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        items_key: str | None = None,
        next_key: str = "next",
        cursor_key: str | None = None,
        cursor_param: str = "cursor",
        max_pages: int | None = None,
    ) -> Iterator[Any]:
        """Yield items, or whole pages when ``items_key`` is omitted.

        The next page is chosen in this order: a string at ``next_key`` (absolute
        or relative URL), a ``cursor_key`` sent back as ``cursor_param``, then a
        ``Link: rel="next"`` header. ``max_pages`` stops a cursor that never ends.
        The same URL and query is not requested twice.
        """
        query = dict(params or {})
        url = self._url(path)
        seen: set[tuple[Any, ...]] = set()
        pages = 0
        while True:
            if max_pages is not None and pages >= max_pages:
                return
            marker = (url, tuple(sorted((str(key), str(value)) for key, value in query.items())))
            if marker in seen:
                return
            seen.add(marker)
            response = self.request("GET", url, params=query or None, headers=headers)
            pages += 1
            payload = _interpret(response)
            if items_key is None:
                yield payload
            else:
                found = _items(payload, items_key)
                if not found:
                    return
                yield from found
            nxt = _next_request(url, query, response, payload, next_key, cursor_key, cursor_param)
            if nxt is None:
                return
            url, query = nxt

    def iter_bytes(
        self,
        path: str,
        *,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Iterator[bytes]:
        """Yield a response body in chunks. The connection closes when iteration ends."""
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        response = self.request("GET", path, params=params, headers=headers, stream=True)
        try:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk:
                    yield chunk
        finally:
            response.close()

    def download(
        self,
        path: str,
        destination: str | Path,
        *,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> int:
        """Stream a response to ``destination``. Returns the number of bytes written.

        The whole download is retried on a transient error. A failed attempt
        deletes its partial file so the next attempt starts clean.
        """
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        dest = Path(destination)
        dest.parent.mkdir(parents=True, exist_ok=True)
        partial = dest.with_name(dest.name + ".partial")
        url = self._url(path)

        def _once() -> int:
            written = 0
            response = None
            try:
                response = self._send("GET", url, params=params, headers=self._headers(headers), stream=True)
                with partial.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=chunk_size):
                        if not chunk:
                            continue
                        handle.write(chunk)
                        written += len(chunk)
                partial.replace(dest)
                return written
            except Exception:
                partial.unlink(missing_ok=True)
                raise
            finally:
                if response is not None:
                    response.close()

        decorated = retry(
            attempts=self.attempts,
            base=self.retry_base,
            cap=self.retry_cap,
            when=_retryable_http,
            **({"sleep": self._sleep} if self._sleep is not None else {}),
        )(_once)
        return decorated()

    def upload(
        self,
        path: str,
        source: str | Path | Any,
        *,
        method: str | None = None,
        field_name: str = "file",
        filename: str | None = None,
        content_type: str | None = None,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        raw: bool = False,
    ) -> Any:
        """Stream a file upload.

        ``raw=False`` sends multipart form data and defaults to POST.
        ``raw=True`` sends the file as the body and defaults to PUT, which is
        retried. A path is reopened on each attempt; a file object is rewound
        when it supports ``seek``. Returns decoded JSON when the response is JSON.
        """
        verb = (method or ("PUT" if raw else "POST")).upper()
        attempts = self.attempts if verb in self.retry_methods else 1
        url = self._url(path)

        def _once() -> Any:
            with _BorrowedFile(source) as (handle, name):
                if hasattr(handle, "seek"):
                    try:
                        handle.seek(0)
                    except OSError:
                        pass
                extra = dict(headers or {})
                if raw:
                    extra.setdefault("Content-Type", content_type or "application/octet-stream")
                    response = self._send(
                        verb,
                        url,
                        params=params,
                        headers=self._headers(extra),
                        data=handle,
                    )
                else:
                    files = {
                        field_name: (filename or name, handle, content_type or "application/octet-stream")
                    }
                    response = self._send(
                        verb,
                        url,
                        params=params,
                        headers=self._headers(extra),
                        files=files,
                    )
            return _interpret(response)

        if attempts <= 1:
            return _once()
        decorated = retry(
            attempts=attempts,
            base=self.retry_base,
            cap=self.retry_cap,
            when=_retryable_http,
            **({"sleep": self._sleep} if self._sleep is not None else {}),
        )(_once)
        return decorated()

    def close(self) -> None:
        """Close the session when this client created it."""
        if self._owns_session:
            self.session.close()

    def __enter__(self) -> ApiClient:
        return self

    def __exit__(self, *exc: object) -> bool:
        self.close()
        return False
