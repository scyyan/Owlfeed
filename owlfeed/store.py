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

from .config import Config, is_http_url
from .fetch import USER_AGENT, FetchResult
from .parse import Entry

SCHEMA_VERSION = 1
MAX_ITEMS = 6000

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


def _clean_previous_item(item: object) -> dict | None:
    """Normalize an item from the previous feed, or drop it if it is malformed."""
    if not isinstance(item, dict):
        return None
    published, first_seen = parse_iso(item.get("published")), parse_iso(item.get("first_seen"))
    fields = (item.get("id"), item.get("source"), item.get("title"))
    if not all(isinstance(f, str) and f for f in fields) or not is_http_url(item.get("url")):
        return None
    if published is None or first_seen is None:
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


def previous_validators(previous: dict | None) -> dict[str, tuple[str | None, str | None]]:
    """ETag/Last-Modified per source from the previous run, for conditional GETs."""
    validators: dict[str, tuple[str | None, str | None]] = {}
    for row in (previous or {}).get("sources", []):
        if isinstance(row, dict) and isinstance(row.get("id"), str):
            etag, modified = row.get("etag"), row.get("last_modified")
            validators[row["id"]] = (
                etag if isinstance(etag, str) else None,
                modified if isinstance(modified, str) else None,
            )
    return validators


def merge(previous: dict | None, config: Config, outcomes: dict[str, SourceOutcome], now: datetime) -> dict:
    sources = config.enabled_sources
    enabled_ids = {s.id for s in sources}
    now_iso = iso(now)

    merged: dict[str, dict] = {}
    for raw in (previous or {}).get("items", []):
        item = _clean_previous_item(raw)
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
    items.sort(key=lambda item: item["title"].casefold())
    items.sort(key=lambda item: (item["published"], item["first_seen"]), reverse=True)
    items = items[:MAX_ITEMS]

    previous_rows = {
        row["id"]: row
        for row in (previous or {}).get("sources", [])
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
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
    }


def write_state(state: dict, path: str | Path) -> None:
    """Write feed.json atomically so a crash never leaves a half-written file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".feed-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
