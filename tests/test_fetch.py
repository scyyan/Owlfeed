import threading

import requests

from owlfeed import fetch as fetch_module
from owlfeed.fetch import FetchResult, fetch, fetch_all

from .conftest import make_source


class FakeRaw:
    def __init__(self, body, on_read=None):
        self._body = body
        self._on_read = on_read

    def read1(self, amt, decode_content=None):
        if self._on_read:
            self._on_read()
        chunk, self._body = self._body[:amt], self._body[amt:]
        return chunk


class FakeResponse:
    def __init__(self, status=200, body=b"<rss/>", headers=None, on_read=None, url="https://a.example/feed", history=()):
        self.status_code = status
        self.headers = headers or {}
        self.raw = FakeRaw(body, on_read)
        self.url = url
        self.history = list(history)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Recorder:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def no_sleep(seconds):
    pass


def test_successful_fetch_returns_body_and_validators():
    get = Recorder(FakeResponse(200, b"<rss>ok</rss>", {"ETag": '"v1"', "Last-Modified": "Wed", "Content-Type": "application/rss+xml"}))
    result = fetch("https://a.example/feed", get=get, sleep=no_sleep)
    assert result == FetchResult(200, b"<rss>ok</rss>", "application/rss+xml", '"v1"', "Wed", None)
    headers = get.calls[0][1]["headers"]
    assert headers["User-Agent"].startswith("Owlfeed/")
    assert "If-None-Match" not in headers


def test_conditional_get_and_not_modified():
    get = Recorder(FakeResponse(304))
    result = fetch("https://a.example/feed", '"v1"', "Wed", get=get, sleep=no_sleep)
    assert result.not_modified and result.etag == '"v1"' and result.error is None
    headers = get.calls[0][1]["headers"]
    assert headers["If-None-Match"] == '"v1"' and headers["If-Modified-Since"] == "Wed"


def test_redirects_that_stay_on_https_are_followed():
    get = Recorder(FakeResponse(200, b"<rss/>", url="https://b.example/feed", history=[FakeResponse(301)]))
    result = fetch("https://a.example/feed", get=get, sleep=no_sleep)
    assert result.error is None and result.content == b"<rss/>"


def test_redirects_to_plain_http_are_refused():
    get = Recorder(FakeResponse(200, b"<rss>evil</rss>", url="http://a.example/feed", history=[FakeResponse(301)]))
    result = fetch("https://a.example/feed", get=get, sleep=no_sleep)
    assert result.error == "redirected to a non-https URL" and result.content is None
    assert len(get.calls) == 1


def test_exhausted_retries_keep_the_last_status():
    get = Recorder(FakeResponse(503), FakeResponse(503))
    result = fetch("https://a.example/feed", get=get, sleep=no_sleep)
    assert (result.status, result.error) == (503, "HTTP 503")


def test_a_timeout_after_a_503_reports_no_status():
    get = Recorder(FakeResponse(503), requests.Timeout())
    result = fetch("https://a.example/feed", get=get, sleep=no_sleep)
    assert result.status is None and result.error


def test_client_errors_are_not_retried():
    get = Recorder(FakeResponse(403))
    result = fetch("https://a.example/feed", get=get, sleep=no_sleep)
    assert result.error == "HTTP 403" and len(get.calls) == 1


def test_server_errors_and_timeouts_are_retried_once():
    get = Recorder(FakeResponse(503), FakeResponse(200, b"<rss/>"))
    assert fetch("https://a.example/feed", get=get, sleep=no_sleep).content == b"<rss/>"

    get = Recorder(requests.Timeout(), requests.Timeout())
    result = fetch("https://a.example/feed", get=get, sleep=no_sleep)
    assert result.error == "timed out" and len(get.calls) == 2


def test_oversized_responses_are_rejected(monkeypatch):
    monkeypatch.setattr(fetch_module, "MAX_BYTES", 10)
    get = Recorder(FakeResponse(200, b"x" * 50))
    assert "larger than" in fetch("https://a.example/feed", get=get, sleep=no_sleep).error

    get = Recorder(FakeResponse(200, b"", {"Content-Length": "999"}))
    assert "larger than" in fetch("https://a.example/feed", get=get, sleep=no_sleep).error


def test_fetch_all_passes_validators_per_source():
    seen = {}

    def fake_fetch(url, etag, last_modified):
        seen[url] = (etag, last_modified)
        return FetchResult(status=200, content=b"<rss/>")

    sources = [make_source("one"), make_source("two")]
    results = fetch_all(sources, {"one": ('"e1"', "lm1")}, fetcher=fake_fetch)
    assert set(results) == {"one", "two"}
    assert seen["https://one.example.com/feed"] == ('"e1"', "lm1")
    assert seen["https://two.example.com/feed"] == (None, None)


def test_slow_drip_bodies_hit_the_download_deadline(monkeypatch):
    clock = iter(range(0, 1000, 7))  # every read takes 7 "seconds"
    monkeypatch.setattr(fetch_module.time, "monotonic", lambda: next(clock))
    get = Recorder(FakeResponse(200, b"x" * 200_000))
    monkeypatch.setattr(fetch_module, "DOWNLOAD_DEADLINE", 20)
    result = fetch("https://a.example/feed", get=get, sleep=no_sleep)
    assert result.error.startswith("timed out") and result.content is None


def test_fetch_all_reports_hung_sources_without_waiting_for_them():
    release = threading.Event()

    def fake_fetch(url, etag, last_modified):
        if "slow" in url:
            release.wait(30)  # simulates a server that never finishes
        return FetchResult(status=200, content=b"<rss/>")

    sources = [make_source("fast"), make_source("slow")]
    try:
        results = fetch_all(sources, fetcher=fake_fetch, deadline=0.5)
    finally:
        release.set()
    assert results["fast"].content == b"<rss/>"
    assert results["slow"].error.startswith("timed out")


def test_fetch_all_contains_unexpected_errors():
    def broken(url, etag, last_modified):
        raise UnicodeError("weird header")

    results = fetch_all([make_source("one")], fetcher=broken)
    assert results["one"].error == "fetch failed (UnicodeError)"
