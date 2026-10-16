"""Parse downloaded feeds into normalized entries."""

from __future__ import annotations

import calendar
import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import feedparser

from .config import Settings, Source, is_http_url
from .text import clean_title, make_summary, truncate

# Dates further ahead than this are treated as bogus (timezone bugs, scheduled posts).
FUTURE_TOLERANCE = timedelta(minutes=10)
TRACKING_PARAMS = frozenset(
    {
        "fbclid", "gclid", "dclid", "yclid", "mc_cid", "mc_eid", "_hsenc", "_hsmi", "mkt_tok",
        "at_medium", "at_campaign",  # BBC
        "traffic_source",  # Al Jazeera
        "maca",  # DW
        "cmpid", "ncid", "sr_share",
    }
)


class FeedParseError(ValueError):
    """Raised when a download is not a usable RSS/Atom feed."""


@dataclass(frozen=True)
class Entry:
    id: str
    url: str
    title: str
    summary: str
    published: datetime | None


def _is_tracking(param: str) -> bool:
    lowered = param.lower()
    return lowered.startswith("utm_") or lowered in TRACKING_PARAMS


def clean_link(url: str) -> str:
    """Drop tracking query parameters; leave every other part of the URL untouched."""
    parts = urlsplit(url)
    if not parts.query:
        return url
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    kept = [(k, v) for k, v in pairs if not _is_tracking(k)]
    if len(kept) == len(pairs):
        return url
    return urlunsplit(parts._replace(query=urlencode(kept, doseq=True)))


def item_id(url: str) -> str:
    """Stable id for an article URL, ignoring scheme, host case and fragment."""
    parts = urlsplit(url)
    key = f"{parts.netloc.lower()}{parts.path or '/'}?{parts.query}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def _alternate_link(entry: dict) -> str | None:
    for link in entry.get("links") or []:
        if isinstance(link, dict) and link.get("rel", "alternate") == "alternate" and link.get("href"):
            return link["href"]
    return None


def entry_link(entry: dict, base: str) -> str | None:
    """The original article URL. feedburner:origLink beats redirector links."""
    for candidate in (entry.get("feedburner_origlink"), entry.get("link"), _alternate_link(entry)):
        if isinstance(candidate, str) and candidate.strip():
            url = urljoin(base, candidate.strip())
            if is_http_url(url):
                return clean_link(url)
    # A guid is only a link when it is already an absolute URL; never resolve opaque ids.
    guid = entry.get("id")
    if isinstance(guid, str) and is_http_url(guid):
        return clean_link(guid.strip())
    return None


def entry_published(entry: dict, now: datetime) -> datetime | None:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        # dict.get skips feedparser's deprecated updated->published aliasing (and its warning).
        value = dict.get(entry, key)
        if not value:
            continue
        try:
            moment = datetime.fromtimestamp(calendar.timegm(value), tz=timezone.utc)
        except (OverflowError, TypeError, ValueError):
            continue
        if moment.year >= 1995 and moment <= now + FUTURE_TOLERANCE:
            return moment.replace(microsecond=0)
    return None


def parse_feed(
    content: bytes,
    source: Source,
    settings: Settings,
    now: datetime,
    content_type: str | None = None,
) -> list[Entry]:
    """Parse feed bytes into the newest entries (at most settings.max_items_per_source)."""
    headers = {"content-type": content_type} if content_type else {}
    parsed = feedparser.parse(content, response_headers=headers)
    if not parsed.entries:
        if not parsed.get("version"):
            problem = parsed.get("bozo_exception")
            detail = f" ({type(problem).__name__})" if problem else ""
            raise FeedParseError(f"not an RSS/Atom feed{detail}")
        return []

    base = parsed.feed.get("link") or source.site
    entries: list[Entry] = []
    seen: set[str] = set()
    for raw in parsed.entries:
        url = entry_link(raw, base)
        if not url:
            continue
        title = clean_title(raw.get("title"))
        if title and any(pattern.search(title) for pattern in source.exclude_title):
            continue
        summary = make_summary(raw, source.summary_from, title, settings.summary_max_chars)
        if not title:
            if not summary:
                continue
            title = truncate(summary, 120)
        entry_id = item_id(url)
        if entry_id in seen:
            continue
        seen.add(entry_id)
        entries.append(Entry(entry_id, url, title, summary, entry_published(raw, now)))

    entries.sort(key=lambda e: e.published or now, reverse=True)
    return entries[: settings.max_items_per_source]
