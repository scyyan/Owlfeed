import requests

from owlfeed import fetch as fetch_module
from owlfeed.fetch import FetchResult, fetch, fetch_all

from .conftest import make_source


class FakeResponse:
    def __init__(self, status=200, body=b"<rss/>", headers=None):
        self.status_code = status
        self._body = body
        self.headers = headers or {}

    def iter_content(self, size):
        for start in range(0, len(self._body), size):
            yield self._body[start : start + size]

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
