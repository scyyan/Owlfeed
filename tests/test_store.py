import json
from datetime import datetime, timedelta, timezone

import pytest
import requests

from owlfeed.config import Config, Settings
from owlfeed.fetch import FetchResult
from owlfeed.parse import Entry
from owlfeed.store import (
    AllSourcesFailed,
    PreviousStateError,
    SourceOutcome,
    iso,
    load_previous_file,
    load_previous_url,
    merge,
    previous_validators,
    write_state,
)

from .conftest import NOW, make_source

ALPHA, BRAVO = make_source("alpha"), make_source("bravo", category="Geopolitics", group="World news")
CONFIG = Config(Settings(retention_days=7), (ALPHA, BRAVO))


def entry(slug, published=NOW - timedelta(hours=1), title=None):
    url = f"https://example.com/{slug}"
    return Entry(id=f"id-{slug}", url=url, title=title or slug.title(), summary=f"Summary of {slug}.", published=published)


def ok(*entries, etag=None):
    return SourceOutcome(FetchResult(status=200, content=b"", etag=etag), list(entries), None)


def failed(message="HTTP 500"):
    return SourceOutcome(FetchResult(error=message), None, message)


NOT_MODIFIED = SourceOutcome(FetchResult(status=304), None, None)


def ids(state):
    return [item["id"] for item in state["items"]]


def test_first_run_builds_sorted_state():
    state = merge(None, CONFIG, {"alpha": ok(entry("a1", NOW - timedelta(hours=3)), entry("a2")), "bravo": ok(entry("b1", NOW - timedelta(hours=2)))}, NOW)
    assert state["version"] == 1 and state["generated_at"] == "2026-10-15T14:00:00Z"
    assert ids(state) == ["id-a2", "id-b1", "id-a1"]
    item = state["items"][0]
    assert item == {
        "id": "id-a2",
        "source": "alpha",
        "title": "A2",
        "url": "https://example.com/a2",
        "summary": "Summary of a2.",
        "published": "2026-10-15T13:00:00Z",
        "first_seen": "2026-10-15T14:00:00Z",
        "date_estimated": False,
    }
    rows = {row["id"]: row for row in state["sources"]}
    assert rows["alpha"]["status"] == "ok" and rows["alpha"]["count"] == 2
    assert rows["bravo"]["category"] == "Geopolitics" and rows["bravo"]["group"] == "World news"


def test_first_seen_is_kept_and_content_refreshed():
    first = merge(None, CONFIG, {"alpha": ok(entry("a1")), "bravo": ok()}, NOW)
    later = NOW + timedelta(minutes=15)
    second = merge(first, CONFIG, {"alpha": ok(entry("a1", title="Updated title")), "bravo": ok()}, later)
    (item,) = second["items"]
    assert item["title"] == "Updated title"
    assert item["first_seen"] == "2026-10-15T14:00:00Z"


def test_undated_entries_use_first_seen_and_stay_stable():
    first = merge(None, CONFIG, {"alpha": ok(entry("nodate", published=None)), "bravo": ok()}, NOW)
    (item,) = first["items"]
    assert item["published"] == item["first_seen"] == "2026-10-15T14:00:00Z"
    assert item["date_estimated"] is True
    second = merge(first, CONFIG, {"alpha": ok(entry("nodate", published=None)), "bravo": ok()}, NOW + timedelta(hours=1))
    assert second["items"][0]["published"] == "2026-10-15T14:00:00Z"


def test_failed_source_keeps_previous_items_and_last_ok():
    first = merge(None, CONFIG, {"alpha": ok(entry("a1"), etag='"e1"'), "bravo": ok(entry("b1"))}, NOW)
    later = NOW + timedelta(minutes=15)
    second = merge(first, CONFIG, {"alpha": failed("HTTP 403"), "bravo": ok(entry("b1"))}, later)
    assert set(ids(second)) == {"id-a1", "id-b1"}
    row = next(r for r in second["sources"] if r["id"] == "alpha")
    assert row["status"] == "error" and row["error"] == "HTTP 403"
    assert row["last_ok"] == "2026-10-15T14:00:00Z" and row["etag"] == '"e1"'


def test_not_modified_keeps_items():
    first = merge(None, CONFIG, {"alpha": ok(entry("a1")), "bravo": ok()}, NOW)
    second = merge(first, CONFIG, {"alpha": NOT_MODIFIED, "bravo": ok()}, NOW + timedelta(minutes=15))
    assert ids(second) == ["id-a1"]
    assert second["sources"][0]["status"] == "ok"


def test_retention_drops_old_items():
    state = merge(None, CONFIG, {"alpha": ok(entry("old", NOW - timedelta(days=8)), entry("new")), "bravo": ok()}, NOW)
    assert ids(state) == ["id-new"]


def test_removed_sources_are_dropped():
    first = merge(None, CONFIG, {"alpha": ok(entry("a1")), "bravo": ok(entry("b1"))}, NOW)
    only_alpha = Config(CONFIG.settings, (ALPHA,))
    second = merge(first, only_alpha, {"alpha": ok(entry("a1"))}, NOW)
    assert ids(second) == ["id-a1"] and [r["id"] for r in second["sources"]] == ["alpha"]


def test_same_article_in_two_sources_is_listed_once():
    shared = entry("shared")
    state = merge(None, CONFIG, {"alpha": ok(shared), "bravo": ok(shared)}, NOW)
    assert ids(state) == ["id-shared"] and state["items"][0]["source"] == "alpha"


def test_malformed_previous_items_are_ignored():
    previous = {
        "version": 1,
        "sources": [],
        "items": [
            {"id": "x", "source": "alpha", "title": "Bad url", "url": "javascript:alert(1)", "published": iso(NOW), "first_seen": iso(NOW)},
            {"id": "y", "source": "alpha", "title": "No dates", "url": "https://example.com/y"},
            "not even a dict",
        ],
    }
    state = merge(previous, CONFIG, {"alpha": ok(), "bravo": ok()}, NOW)
    assert state["items"] == []


def test_all_sources_failing_raises():
    with pytest.raises(AllSourcesFailed):
        merge(None, CONFIG, {"alpha": failed(), "bravo": failed()}, NOW)


def test_previous_validators():
    state = merge(None, CONFIG, {"alpha": ok(etag='"e1"'), "bravo": ok()}, NOW)
    assert previous_validators(state) == {"alpha": ('"e1"', None), "bravo": (None, None)}
    assert previous_validators(None) == {}


class FakeResponse:
    def __init__(self, status, payload=None, text=None):
        self.status_code = status
        self._payload = payload
        self._text = text

    def json(self):
        if self._text is not None:
            return json.loads(self._text)
        return self._payload


def test_load_previous_url_handles_first_run_and_failures():
    state = merge(None, CONFIG, {"alpha": ok(entry("a1")), "bravo": ok()}, NOW)
    assert load_previous_url("u", get=lambda *a, **k: FakeResponse(200, state)) == state
    assert load_previous_url("u", get=lambda *a, **k: FakeResponse(404)) is None
    # A wrong schema version is treated as a fresh start rather than an error.
    assert load_previous_url("u", get=lambda *a, **k: FakeResponse(200, {"version": 99})) is None
    with pytest.raises(PreviousStateError):
        load_previous_url("u", get=lambda *a, **k: FakeResponse(503))
    with pytest.raises(PreviousStateError):
        load_previous_url("u", get=lambda *a, **k: FakeResponse(200, text="<html>"))

    def boom(*args, **kwargs):
        raise requests.ConnectionError("down")

    with pytest.raises(PreviousStateError):
        load_previous_url("u", get=boom)


def test_write_and_load_previous_file(tmp_path):
    state = merge(None, CONFIG, {"alpha": ok(entry("a1")), "bravo": ok()}, NOW)
    path = tmp_path / "data" / "feed.json"
    write_state(state, path)
    assert load_previous_file(path) == state
    assert load_previous_file(tmp_path / "missing.json") is None
    assert not list(path.parent.glob(".feed-*"))  # no temp files left behind
