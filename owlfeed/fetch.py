"""Download feeds politely: timeouts, conditional GET, size and time caps, one retry."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Iterable
from urllib.parse import urljoin

import requests
import urllib3

from . import __version__
from .config import Source

USER_AGENT = f"Owlfeed/{__version__} (+https://github.com/scyyan/Owlfeed; RSS reader)"
ACCEPT = (
    "application/rss+xml, application/atom+xml, application/rdf+xml;q=0.9, "
    "application/xml;q=0.9, text/xml;q=0.9, */*;q=0.5"
)
TIMEOUT = (10, 20)  # (connect, read) seconds, per socket operation
DOWNLOAD_DEADLINE = 60.0  # seconds for a whole response body, however slowly it trickles in
FETCH_ALL_DEADLINE = 180.0  # seconds for every source together; stragglers are reported as timed out
MAX_BYTES = 10 * 1024 * 1024
RETRY_BACKOFF_SECONDS = 2.0  # wait before retry n is n times this
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
MAX_REDIRECTS = 5
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


class _TooSlow(Exception):
    pass


def _read_limited(response: requests.Response) -> bytes:
    """Read the (decompressed) body, enforcing both the size cap and a wall-clock deadline."""
    deadline = DOWNLOAD_DEADLINE
    declared = response.headers.get("Content-Length", "")
    if declared.isdigit() and int(declared) > MAX_BYTES:
        raise _TooLarge
    started = time.monotonic()
    chunks: list[bytes] = []
    size = 0
    while True:
        if time.monotonic() - started > deadline:
            raise _TooSlow
        # read1 returns as soon as any data arrives, so a slow drip cannot stall the deadline check.
        chunk = response.raw.read1(64 * 1024, decode_content=True)
        if not chunk:
            break
        size += len(chunk)
        if size > MAX_BYTES:
            raise _TooLarge
        chunks.append(chunk)
    return b"".join(chunks)


def _describe(exc: Exception) -> str:
    if isinstance(exc, (requests.Timeout, urllib3.exceptions.TimeoutError)):
        return "timed out"
    if isinstance(exc, (requests.exceptions.SSLError, urllib3.exceptions.SSLError)):
        return "TLS/certificate error"
    if isinstance(exc, requests.TooManyRedirects):
        return "too many redirects"
    if isinstance(exc, urllib3.exceptions.DecodeError):
        return "invalid compressed response"
    if isinstance(exc, (requests.ConnectionError, urllib3.exceptions.HTTPError)):
        return "connection failed"
    return f"request failed ({type(exc).__name__})"


class _ManualRedirectSession(requests.Session):
    """A session that never resolves redirects itself.

    requests reads (and decompresses) a redirect's whole body while resolving it, even with
    allow_redirects=False (it still works out Response.next), before our size cap and download
    deadline apply. With no redirect target it reads nothing; _open follows Location instead.
    """

    def get_redirect_target(self, resp: requests.Response) -> None:
        return None


def _get(url: str, **kwargs) -> requests.Response:
    # Same pattern as requests.get: a streamed response keeps its connection after the session closes.
    with _ManualRedirectSession() as session:
        return session.get(url, **kwargs)


def _open(get: Callable[..., requests.Response], url: str, headers: dict[str, str]) -> tuple[requests.Response | None, str | None]:
    """GET url, following redirects by hand. Returns (response, None) or (None, error).

    Each redirect is closed unread, and every hop (not just the last) must stay on https, since
    feeds are https (see config.py).
    """
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        response = get(current, headers=headers, timeout=TIMEOUT, stream=True, allow_redirects=False)
        location = (response.headers.get("Location") or "").strip()
        if response.status_code not in REDIRECT_STATUSES or not location:
            return response, None
        response.close()
        try:
            current = urljoin(current, location)
        except ValueError:
            return None, "invalid redirect"
        if not current.lower().startswith("https://"):
            return None, "redirected to a non-https URL"
    return None, "too many redirects"


def fetch(
    url: str,
    etag: str | None = None,
    last_modified: str | None = None,
    *,
    get: Callable[..., requests.Response] = _get,
    sleep: Callable[[float], None] = time.sleep,
    retries: int = 1,
) -> FetchResult:
    headers = {"User-Agent": USER_AGENT, "Accept": ACCEPT}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified

    retryable_error: str | None = None
    last_status: int | None = None  # kept so "HTTP 503" still reports 503 once the retries run out
    for attempt in range(retries + 1):
        retryable_error, last_status = None, None
        try:
            opened, redirect_error = _open(get, url, headers)
            if redirect_error:
                return FetchResult(error=redirect_error)
            with opened as response:
                status = response.status_code
                if status == 304:
                    return FetchResult(
                        status=304,
                        etag=response.headers.get("ETag") or etag,
                        last_modified=response.headers.get("Last-Modified") or last_modified,
                    )
                if status in RETRY_STATUSES:
                    retryable_error, last_status = f"HTTP {status}", status
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
        except _TooSlow:
            return FetchResult(error=f"timed out (download took over {DOWNLOAD_DEADLINE:.0f} s)")
        except (requests.Timeout, requests.ConnectionError, urllib3.exceptions.HTTPError) as exc:
            retryable_error = _describe(exc)
        except requests.RequestException as exc:
            return FetchResult(error=_describe(exc))
        if attempt < retries:
            sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
    return FetchResult(status=last_status, error=retryable_error)


def fetch_all(
    sources: Iterable[Source],
    validators: dict[str, tuple[str | None, str | None]] | None = None,
    *,
    fetcher: Callable[..., FetchResult] = fetch,
    deadline: float = FETCH_ALL_DEADLINE,
) -> dict[str, FetchResult]:
    """Fetch every source concurrently. Never raises for a single bad feed.

    Daemon threads plus an overall deadline mean one hung server can neither block the
    others' results nor keep the process alive after the build has finished.
    """
    sources = list(sources)
    validators = validators or {}
    results: dict[str, FetchResult] = {}
    lock = threading.Lock()
    slots = threading.BoundedSemaphore(WORKERS)

    def run(source: Source) -> None:
        with slots:
            etag, last_modified = validators.get(source.id, (None, None))
            try:
                result = fetcher(source.feed, etag, last_modified)
            except Exception as exc:  # noqa: BLE001 - any bug or odd library error stays per-source
                result = FetchResult(error=f"fetch failed ({type(exc).__name__})")
        with lock:
            results[source.id] = result

    threads = [threading.Thread(target=run, args=(s,), name=f"fetch-{s.id}", daemon=True) for s in sources]
    for thread in threads:
        thread.start()
    stop_at = time.monotonic() + deadline
    for thread in threads:
        thread.join(max(0.0, stop_at - time.monotonic()))
    with lock:
        return {
            s.id: results.get(s.id, FetchResult(error=f"timed out (no complete response within {deadline:.0f} s)"))
            for s in sources
        }
