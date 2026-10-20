"""Restore the previous feed.json, merge in fresh entries and write the new one."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import requests

from .config import FUTURE_TOLERANCE, Config, is_http_url
from .fetch import USER_AGENT, FetchResult
from .parse import Entry

SCHEMA_VERSION = 1
MAX_ITEMS = 6000
# Expired undated items are remembered this long after their feed last listed them.
TOMBSTONE_DAYS = 30
# Far more than the feeds can list at once; only bounds a corrupt or injected restored state.
MAX_TOMBSTONES = 5000
# Restored items dated later than this are corrupt (or injected) and are dropped.

log = logging.getLogger(__name__)


class PreviousStateError(RuntimeError):
    """The previous feed exists but could not be read; the run must not overwrite it."""


class AllSourcesFailed(RuntimeError):
    """Every source failed, which usually means the runner has no network."""


@dataclass(frozen=True)
class SourceOutcome:
    result: FetchResult
    entries: list[Entry] | None = None  # None when nothing was parsed (error or 304)
    error: str | None = None


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def validate_previous(data: object) -> dict | None:
    if (
        isinstance(data, dict)
        and data.get("version") == SCHEMA_VERSION
        and isinstance(data.get("items"), list)
        and isinstance(data.get("sources"), list)
    ):
        return data
    log.warning("Previous feed has an unexpected format; starting fresh")
    return None


def load_previous_url(url: str, *, get: Callable[..., requests.Response] = requests.get) -> dict | None:
    """Download the deployed feed.json. 404 means first run; any other failure raises."""
    try:
        response = get(url, headers={"User-Agent": USER_AGENT, "Cache-Control": "no-cache"}, timeout=(10, 30))
    except requests.RequestException as exc:
        raise PreviousStateError(f"could not download the previous feed ({type(exc).__name__})") from exc
    if response.status_code == 404:
        log.info("No previous feed at %s; starting fresh", url)
        return None
    if response.status_code != 200:
        raise PreviousStateError(f"previous feed returned HTTP {response.status_code}")
    try:
        data = response.json()
    except ValueError as exc:
        raise PreviousStateError("previous feed is not valid JSON") from exc
    return validate_previous(data)


def load_previous_file(path: str | Path) -> dict | None:
    path = Path(path)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PreviousStateError(f"cannot read previous feed {path}: {exc}") from exc
    return validate_previous(data)


def _clean_previous_item(item: object, now: datetime) -> dict | None:
    """Normalize an item from the previous feed, or drop it if it is malformed."""
    if not isinstance(item, dict):
        return None
    published, first_seen = parse_iso(item.get("published")), parse_iso(item.get("first_seen"))
    fields = (item.get("id"), item.get("source"), item.get("title"))
    if not all(isinstance(f, str) and f for f in fields) or not is_http_url(item.get("url")):
        return None
    if published is None or first_seen is None:
        return None
    if max(published, first_seen) > now + FUTURE_TOLERANCE:
        return None
    return {
        "id": item["id"],
        "source": item["source"],
        "title": item["title"],
        "url": item["url"],
        "summary": item.get("summary") if isinstance(item.get("summary"), str) else "",
        "published": iso(published),
        "first_seen": iso(first_seen),
        "date_estimated": bool(item.get("date_estimated")),
    }


def _previous_source_rows(previous: dict | None) -> dict[str, dict]:
    """The previous run's source rows by id, skipping malformed ones."""
    return {
        row["id"]: row
        for row in (previous or {}).get("sources", [])
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }


def previous_validators(previous: dict | None) -> dict[str, tuple[str | None, str | None]]:
    """ETag/Last-Modified per source from the previous run, for conditional GETs."""
    validators: dict[str, tuple[str | None, str | None]] = {}
    for source_id, row in _previous_source_rows(previous).items():
        etag, modified = row.get("etag"), row.get("last_modified")
        validators[source_id] = (
            etag if isinstance(etag, str) else None,
            modified if isinstance(modified, str) else None,
        )
    return validators


def merge(previous: dict | None, config: Config, outcomes: dict[str, SourceOutcome], now: datetime) -> dict:
    sources = config.enabled_sources
    enabled_ids = {s.id for s in sources}
    now_iso = iso(now)
    previous_rows = _previous_source_rows(previous)

    # Undated items that aged out ("tombstones"), so they are not re-created as brand-new items:
    # {id: {"source": id, "since": iso}}. Malformed entries are ignored.
    raw_expired = (previous or {}).get("expired")
    expired_before: dict[str, dict] = {}
    for item_id, mark in (raw_expired.items() if isinstance(raw_expired, dict) else []):
        if not (isinstance(item_id, str) and isinstance(mark, dict)):
            continue
        source_id, since = mark.get("source"), parse_iso(mark.get("since"))
        if isinstance(source_id, str) and source_id in enabled_ids and since and since <= now + FUTURE_TOLERANCE:
            expired_before[item_id] = {"source": source_id, "since": iso(since)}

    merged: dict[str, dict] = {}
    for raw in (previous or {}).get("items", []):
        item = _clean_previous_item(raw, now)
        if item and item["source"] in enabled_ids and item["id"] not in merged:
            merged[item["id"]] = item

    for source in sources:
        outcome = outcomes.get(source.id)
        if outcome is None or outcome.entries is None:
            continue
        for entry in outcome.entries:
            existing = merged.get(entry.id)
            if existing and existing["source"] != source.id:
                continue  # the same article is already listed under another source
            tombstone = expired_before.get(entry.id)
            if not existing and entry.published is None and tombstone and tombstone["source"] == source.id:
                continue  # an undated item that already had its 7 days
            first_seen = existing["first_seen"] if existing else now_iso
            if entry.published is not None:
                published, estimated = iso(entry.published), False
            elif existing:
                published, estimated = existing["published"], existing["date_estimated"]
            else:
                published, estimated = first_seen, True
            merged[entry.id] = {
                "id": entry.id,
                "source": source.id,
                "title": entry.title,
                "url": entry.url,
                "summary": entry.summary,
                "published": published,
                "first_seen": first_seen,
                "date_estimated": estimated,
            }

    cutoff = iso(now - timedelta(days=config.settings.retention_days))
    items = [item for item in merged.values() if item["published"] >= cutoff]

    fresh_ids = {
        source_id: {entry.id for entry in outcome.entries}
        for source_id, outcome in outcomes.items()
        if outcome is not None and outcome.entries is not None
    }
    # When each source last answered (200 or 304) before this run. Tombstones the feed listed then were
    # stamped with that time, so a 304 now (the same feed again) still lists exactly those.
    last_ok_before = {
        source_id: iso(last_ok)
        for source_id, row in previous_rows.items()
        if (last_ok := parse_iso(row.get("last_ok"))) is not None
    }
    tombstone_cutoff = iso(now - timedelta(days=TOMBSTONE_DAYS))
    expired: dict[str, dict] = {}
    for item_id, mark in expired_before.items():
        outcome = outcomes.get(mark["source"])
        listed = fresh_ids.get(mark["source"])
        unchanged = outcome is not None and outcome.error is None and outcome.entries is None  # a 304
        prior_ok = last_ok_before.get(mark["source"])
        if (listed is not None and item_id in listed) or (unchanged and (prior_ok is None or mark["since"] >= prior_ok)):
            # Still in the feed (or in the unchanged feed): the 30 days count from the last time it
            # was listed, so one short response later cannot revive it.
            expired[item_id] = {"source": mark["source"], "since": now_iso}
        elif listed is None or mark["since"] >= tombstone_cutoff:
            # Kept while the source fails, so a feed that is down for a month cannot bring its old
            # undated items back as "new" afterwards.
            expired[item_id] = mark
    for item in merged.values():
        if item["published"] < cutoff and item["date_estimated"] and item["id"] not in expired:
            expired[item["id"]] = {"source": item["source"], "since": now_iso}
    if len(expired) > MAX_TOMBSTONES:
        newest = sorted(expired.items(), key=lambda pair: pair[1]["since"], reverse=True)
        expired = dict(newest[:MAX_TOMBSTONES])
    items.sort(key=lambda item: item["title"].casefold())
    items.sort(key=lambda item: (item["published"], item["first_seen"]), reverse=True)
    items = items[:MAX_ITEMS]

    counts = Counter(item["source"] for item in items)
    rows = []
    for source in sources:
        outcome = outcomes.get(source.id)
        prior = previous_rows.get(source.id, {})
        ok = outcome is not None and outcome.error is None
        if ok:
            etag, modified = outcome.result.etag, outcome.result.last_modified
        else:
            etag, modified = prior.get("etag"), prior.get("last_modified")
        rows.append(
            {
                "id": source.id,
                "name": source.name,
                "site": source.site,
                "category": source.category,
                "group": source.group,
                "status": "ok" if ok else "error",
                "error": None if ok else (outcome.error if outcome else "not fetched"),
                "last_ok": now_iso if ok else prior.get("last_ok"),
                "etag": etag,
                "last_modified": modified,
                "count": counts[source.id],
            }
        )

    if sources and all(row["status"] == "error" for row in rows):
        raise AllSourcesFailed("every source failed to load")

    return {
        "version": SCHEMA_VERSION,
        "generated_at": now_iso,
        "retention_days": config.settings.retention_days,
        "sources": rows,
        "items": items,
        "expired": expired,
    }


def write_state(state: dict, path: str | Path) -> None:
    """Write feed.json atomically so a crash never leaves a half-written file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".feed-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, separators=(",", ":"))
        os.chmod(tmp, 0o644)  # mkstemp creates 0600; the published file must be world-readable
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
