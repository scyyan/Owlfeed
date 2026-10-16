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


def test_expired_undated_items_do_not_come_back_as_new():
    nodate = entry("nodate", published=None)
    first = merge(None, CONFIG, {"alpha": ok(nodate), "bravo": ok()}, NOW)
    week_later = NOW + timedelta(days=8)
    second = merge(first, CONFIG, {"alpha": ok(nodate), "bravo": ok()}, week_later)
    assert ids(second) == [] and second["expired"] == {"id-nodate": {"source": "alpha", "since": iso(week_later)}}
    # A short or empty response does not erase the tombstone...
    glitch = merge(second, CONFIG, {"alpha": ok(), "bravo": ok()}, week_later + timedelta(minutes=15))
    assert "id-nodate" in glitch["expired"]
    third = merge(glitch, CONFIG, {"alpha": ok(nodate), "bravo": ok()}, week_later + timedelta(minutes=30))
    assert ids(third) == []
    # ...but it lapses after 30 days once the feed no longer lists the item.
    later = merge(third, CONFIG, {"alpha": ok(), "bravo": ok()}, week_later + timedelta(days=31))
    assert later["expired"] == {}
    # While the feed keeps listing it, the tombstone stays even after 30 days, and its clock restarts.
    month_later = week_later + timedelta(days=31)
    still_listed = merge(third, CONFIG, {"alpha": ok(nodate), "bravo": ok()}, month_later)
    assert ids(still_listed) == [] and still_listed["expired"]["id-nodate"]["since"] == iso(month_later)
    gap = merge(still_listed, CONFIG, {"alpha": ok(), "bravo": ok()}, month_later + timedelta(days=1))
    assert "id-nodate" in gap["expired"]


def test_tombstones_survive_while_a_source_is_not_reread():
    nodate = entry("nodate", published=None)
    first = merge(None, CONFIG, {"alpha": ok(nodate), "bravo": ok()}, NOW)
    expired_at = NOW + timedelta(days=8)
    state = merge(first, CONFIG, {"alpha": ok(nodate), "bravo": ok()}, expired_at)
    # A month and more of 304s and failures re-reads nothing, so the tombstone must stay...
    for day, outcome in ((20, NOT_MODIFIED), (40, failed()), (45, NOT_MODIFIED)):
        state = merge(state, CONFIG, {"alpha": outcome, "bravo": ok()}, expired_at + timedelta(days=day))
        assert "id-nodate" in state["expired"]
    # ...so when the feed changes again, its old undated item does not come back as new.
    back = expired_at + timedelta(days=50)
    changed = merge(state, CONFIG, {"alpha": ok(nodate, entry("fresh", back)), "bravo": ok()}, back)
    assert ids(changed) == ["id-fresh"]


def test_a_short_response_after_a_month_of_304s_keeps_tombstones():
    nodate = entry("nodate", published=None)
    first = merge(None, CONFIG, {"alpha": ok(nodate), "bravo": ok()}, NOW)
    expired_at = NOW + timedelta(days=8)
    state = merge(first, CONFIG, {"alpha": ok(nodate), "bravo": ok()}, expired_at)
    state = merge(state, CONFIG, {"alpha": NOT_MODIFIED, "bravo": ok()}, expired_at + timedelta(days=40))
    short = merge(state, CONFIG, {"alpha": ok(), "bravo": ok()}, expired_at + timedelta(days=41))
    assert "id-nodate" in short["expired"]
    back = merge(short, CONFIG, {"alpha": ok(nodate), "bravo": ok()}, expired_at + timedelta(days=42))
    assert ids(back) == []


def test_malformed_tombstones_and_future_items_are_ignored():
    previous = {
        "version": 1,
        "sources": [],
        "expired": {
            "x": "alpha",
            "y": {"source": "alpha"},
            "z": ["not", "a", "dict"],
            5: {},
            "list-source": {"source": ["alpha"], "since": iso(NOW)},
            "dict-source": {"source": {"id": "alpha"}, "since": iso(NOW)},
            "future": {"source": "alpha", "since": "2099-01-01T00:00:00Z"},
        },
        "items": [
            {"id": "f", "source": "alpha", "title": "From the future", "url": "https://evil.example/f",
             "published": "2099-01-01T00:00:00Z", "first_seen": "2099-01-01T00:00:00Z"},
        ],
    }
    state = merge(previous, CONFIG, {"alpha": ok(), "bravo": ok()}, NOW)
    assert state["items"] == [] and state["expired"] == {}


def test_written_feed_is_world_readable(tmp_path):
    state = merge(None, CONFIG, {"alpha": ok(entry("a1")), "bravo": ok()}, NOW)
    path = tmp_path / "feed.json"
    write_state(state, path)
    assert path.stat().st_mode & 0o777 == 0o644


def test_tombstone_dates_are_normalized_and_their_number_is_capped(monkeypatch):
    previous = {
        "version": 1,
        "sources": [],
        "items": [],
        "expired": {"offset": {"source": "alpha", "since": "2026-10-15T16:00:00+02:00"}},
    }
    state = merge(previous, CONFIG, {"alpha": ok(), "bravo": ok()}, NOW)
    assert state["expired"] == {"offset": {"source": "alpha", "since": "2026-10-15T14:00:00Z"}}

    monkeypatch.setattr("owlfeed.store.MAX_TOMBSTONES", 2)
    previous["expired"] = {
        f"t{n}": {"source": "alpha", "since": iso(NOW - timedelta(days=n))} for n in range(5)
    }
    state = merge(previous, CONFIG, {"alpha": ok(), "bravo": ok()}, NOW)
    assert sorted(state["expired"]) == ["t0", "t1"]


def test_a_304_does_not_keep_tombstones_of_items_the_feed_dropped():
    nodate = entry("nodate", published=None)
    first = merge(None, CONFIG, {"alpha": ok(nodate), "bravo": ok()}, NOW)
    expired_at = NOW + timedelta(days=8)
    state = merge(first, CONFIG, {"alpha": ok(nodate), "bravo": ok()}, expired_at)
    # The feed drops the item, then stops changing for a while.
    state = merge(state, CONFIG, {"alpha": ok(entry("other", published=None)), "bravo": ok()}, expired_at + timedelta(days=1))
    for day in (2, 20, 35):
        state = merge(state, CONFIG, {"alpha": NOT_MODIFIED, "bravo": ok()}, expired_at + timedelta(days=day))
    assert state["expired"]["id-nodate"]["since"] == iso(expired_at)  # not refreshed by the 304s
    later = merge(state, CONFIG, {"alpha": ok(entry("other", published=None)), "bravo": ok()}, expired_at + timedelta(days=36))
    assert "id-nodate" not in later["expired"]
