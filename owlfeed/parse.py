"""Parse downloaded feeds into normalized entries."""

from __future__ import annotations

import calendar
import hashlib
import io
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import feedparser

from .config import Settings, Source, is_http_url
from .text import clean_title, make_summary, truncate

# Dates further ahead than this are treated as bogus (timezone bugs, scheduled posts).
FUTURE_TOLERANCE = timedelta(minutes=10)
FALLBACK_DATE_FORMATS = (
    "%a, %d %b %Y %H:%M:%S",  # RFC 822 without a zone, which feedparser rejects
    "%a, %d %b %Y %H:%M",
    "%d %b %Y %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%A, %B %d, %Y - %H:%M",
    "%B %d, %Y - %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%A, %d %B %Y",
    "%d %B %Y",
    "%B %d, %Y",
)
# A date string that names its own offset or zone; the source's configured zone does not apply.
_HAS_ZONE = re.compile(r"(?:\d\s*(?:Z|[+-]\d{2}:?\d{2})|\b(?:GMT|UTC|UT|[ECMP][SD]T|Z)\b)\s*$", re.IGNORECASE)
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


def _plausible(moment: datetime, now: datetime) -> bool:
    return moment.year >= 1995 and moment <= now + FUTURE_TOLERANCE


def parse_loose_date(text: str, tz: tzinfo = timezone.utc) -> datetime | None:
    """Dates feedparser does not understand, e.g. Drupal's "Monday, October 12, 2026 - 21:44"."""
    text = " ".join(text.split())
    for fmt in FALLBACK_DATE_FORMATS:
        try:
            moment = datetime.strptime(text, fmt)
        except ValueError:
            continue
        return moment.replace(tzinfo=tz).astimezone(timezone.utc)
    return None


def entry_published(entry: dict, now: datetime, tz: tzinfo = timezone.utc) -> datetime | None:
    # feedparser silently treats zone-less dates as UTC; read those in the source's own zone first.
    for key in ("published", "updated", "created"):
        raw = dict.get(entry, key)
        if isinstance(raw, str) and raw.strip() and not _HAS_ZONE.search(raw.strip()):
            moment = parse_loose_date(raw, tz)
            if moment and _plausible(moment, now):
                return moment
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        # dict.get skips feedparser's deprecated updated->published aliasing (and its warning).
        value = dict.get(entry, key)
        if not value:
            continue
        try:
            moment = datetime.fromtimestamp(calendar.timegm(value), tz=timezone.utc)
        except (OverflowError, TypeError, ValueError):
            continue
        if _plausible(moment, now):
            return moment.replace(microsecond=0)
    for key in ("published", "updated", "created"):
        raw = dict.get(entry, key)
        if isinstance(raw, str) and not dict.get(entry, f"{key}_parsed"):
            moment = parse_loose_date(raw, tz)
            if moment and _plausible(moment, now):
                return moment
    return None


def _entry(raw: dict, base: str, source: Source, settings: Settings, now: datetime) -> Entry | None:
    url = entry_link(raw, base)
    if not url:
        return None
    title = clean_title(raw.get("title"))
    if title and any(pattern.search(title) for pattern in source.exclude_title):
        return None
    summary = make_summary(raw, source.summary_from, title, settings.summary_max_chars)
    if not title:
        if not summary:
            return None
        title = truncate(summary, 120)
    return Entry(item_id(url), url, title, summary, entry_published(raw, now, source.tz))


def parse_feed(
    content: bytes,
    source: Source,
    settings: Settings,
    now: datetime,
    content_type: str | None = None,
) -> list[Entry]:
    """Parse feed bytes into the newest entries (at most settings.max_items_per_source)."""
    headers = {"content-type": content_type} if content_type else {}
    # Always hand feedparser a stream: given raw bytes it first tries to open them as a local file path.
    parsed = feedparser.parse(io.BytesIO(content), response_headers=headers)
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
        try:
            entry = _entry(raw, base, source, settings, now)
        except ValueError:
            continue  # e.g. a malformed URL; one bad entry must not sink the whole feed
        if entry is None or entry.id in seen:
            continue
        seen.add(entry.id)
        entries.append(entry)

    # Newest dated entries first; undated ones keep their feed order after them.
    dated = sorted((e for e in entries if e.published), key=lambda e: e.published, reverse=True)
    undated = [e for e in entries if not e.published]
    return (dated + undated)[: settings.max_items_per_source]
