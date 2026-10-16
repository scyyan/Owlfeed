"""Download feeds politely: timeouts, conditional GET, a size cap and one retry."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, Iterable

import requests

from . import __version__
from .config import Source

USER_AGENT = f"Owlfeed/{__version__} (+https://github.com/scyyan/Owlfeed; RSS reader)"
ACCEPT = (
    "application/rss+xml, application/atom+xml, application/rdf+xml;q=0.9, "
    "application/xml;q=0.9, text/xml;q=0.9, */*;q=0.5"
)
TIMEOUT = (10, 20)  # (connect, read) seconds
MAX_BYTES = 10 * 1024 * 1024
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
WORKERS = 8


@dataclass(frozen=True)
class FetchResult:
    status: int | None = None
    content: bytes | None = None
    content_type: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    error: str | None = None

    @property
    def not_modified(self) -> bool:
        return self.status == 304


class _TooLarge(Exception):
    pass


def _read_limited(response: requests.Response) -> bytes:
    declared = response.headers.get("Content-Length", "")
    if declared.isdigit() and int(declared) > MAX_BYTES:
        raise _TooLarge
    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_content(64 * 1024):
        size += len(chunk)
        if size > MAX_BYTES:
            raise _TooLarge
        chunks.append(chunk)
    return b"".join(chunks)


def _describe(exc: requests.RequestException) -> str:
    if isinstance(exc, requests.Timeout):
        return "timed out"
    if isinstance(exc, requests.exceptions.SSLError):
        return "TLS/certificate error"
    if isinstance(exc, requests.TooManyRedirects):
        return "too many redirects"
    if isinstance(exc, requests.ConnectionError):
        return "connection failed"
    return f"request failed ({type(exc).__name__})"


def fetch(
    url: str,
    etag: str | None = None,
    last_modified: str | None = None,
    *,
    get: Callable[..., requests.Response] = requests.get,
    sleep: Callable[[float], None] = time.sleep,
    retries: int = 1,
) -> FetchResult:
    headers = {"User-Agent": USER_AGENT, "Accept": ACCEPT}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified

    for attempt in range(retries + 1):
        retryable_error: str | None = None
        try:
            with get(url, headers=headers, timeout=TIMEOUT, stream=True, allow_redirects=True) as response:
                status = response.status_code
                if status == 304:
                    return FetchResult(
                        status=304,
                        etag=response.headers.get("ETag") or etag,
                        last_modified=response.headers.get("Last-Modified") or last_modified,
                    )
                if status in RETRY_STATUSES:
                    retryable_error = f"HTTP {status}"
                elif status >= 400:
                    return FetchResult(status=status, error=f"HTTP {status}")
                else:
                    return FetchResult(
                        status=status,
                        content=_read_limited(response),
                        content_type=response.headers.get("Content-Type"),
                        etag=response.headers.get("ETag"),
                        last_modified=response.headers.get("Last-Modified"),
                    )
        except _TooLarge:
            return FetchResult(error=f"response larger than {MAX_BYTES // (1024 * 1024)} MB")
        except (requests.Timeout, requests.ConnectionError) as exc:
            retryable_error = _describe(exc)
        except requests.RequestException as exc:
            return FetchResult(error=_describe(exc))
        if attempt < retries:
            sleep(2.0 * (attempt + 1))
    return FetchResult(error=retryable_error)


def fetch_all(
    sources: Iterable[Source],
    validators: dict[str, tuple[str | None, str | None]] | None = None,
    *,
    fetcher: Callable[..., FetchResult] = fetch,
) -> dict[str, FetchResult]:
    """Fetch every source concurrently. Never raises for a single bad feed."""
    sources = list(sources)
    validators = validators or {}

    def run(source: Source) -> FetchResult:
        etag, last_modified = validators.get(source.id, (None, None))
        return fetcher(source.feed, etag, last_modified)

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = list(pool.map(run, sources))
    return {source.id: result for source, result in zip(sources, results)}
