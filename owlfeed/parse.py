"""Parse downloaded feeds into normalized entries."""

from __future__ import annotations

import calendar
import hashlib
import io
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from urllib.parse import unquote_plus, urljoin, urlsplit, urlunsplit

import feedparser

from .config import FUTURE_TOLERANCE, Settings, Source, is_http_url
from .text import clean_title, make_summary, truncate

# Tried in order when feedparser cannot read a date. Day and month names assume an English (or C)
# locale, which is what the GitHub runners use.
FALLBACK_DATE_FORMATS = (
    "%a, %d %b %Y %H:%M:%S",  # RFC 822 without a zone, which feedparser rejects
    "%a, %d %b %Y %H:%M",
    "%d %b %Y %H:%M:%S",
    "%d %b %Y %H:%M",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%A, %B %d, %Y - %H:%M",
    "%B %d, %Y - %H:%M",
    "%Y-%m-%d",
    "%A, %d %B %Y",
    "%d %B %Y",
    "%B %d, %Y",
)
# A date string that names its own offset or zone; the source's configured zone does not apply.
# The names are the ones feedparser converts itself (military letters included).
_HAS_ZONE = re.compile(
    r"(?:\d\s*(?:Z|[+-]\d{2}:?\d{2})|:\d{2}(?:\.\d+)?\s*[+-]\d{2}"
    r"|\b(?:GMT|UTC|UT|[ECMP][SDT]?T|A[DS]?T|MES?T|[AZNMY])\b)\s*$",
    re.IGNORECASE,
)
# Zone abbreviations feedparser does not know (it would silently read them as UTC).
NAMED_ZONES = {
    name: timezone(timedelta(hours=hours), name)
    for name, hours in {
        "WET": 0, "WEST": 1, "BST": 1, "CET": 1, "CEST": 2, "EET": 2, "EEST": 3, "MSK": 3,
        "SGT": 8, "HKT": 8, "JST": 9, "KST": 9, "AEST": 10, "AEDT": 11, "NZST": 12, "NZDT": 13,
    }.items()
}
_NAMED_ZONE = re.compile(r"\s(" + "|".join(NAMED_ZONES) + r")\s*$")
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
    # Drop whole "key=value" segments and keep the others byte for byte: re-encoding would change
    # ";" separators, %-escapes and bare keys ("?12345"), and so the link and its item id.
    segments = parts.query.split("&")
    kept = [seg for seg in segments if not _is_tracking(unquote_plus(seg.split("=", 1)[0]))]
    if len(kept) == len(segments):
        return url
    return urlunsplit(parts._replace(query="&".join(kept)))


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
    link = entry.get("link")
    if entry.get("guidislink") and not is_http_url(link):
        # feedparser copied a <guid> into link; an opaque id ("abc-123") is not a relative URL.
        link = None
    for candidate in (entry.get("feedburner_origlink"), link, _alternate_link(entry)):
        if isinstance(candidate, str) and candidate.strip():
            try:
                url = urljoin(base, candidate.strip())
                if is_http_url(url):
                    return clean_link(url)
            except ValueError:
                continue  # malformed (e.g. a broken IPv6 host); try the next candidate
    # A guid is only a link when it is already an absolute URL; never resolve opaque ids.
    guid = entry.get("id")
    if isinstance(guid, str) and is_http_url(guid):
        try:
            return clean_link(guid.strip())
        except ValueError:
            return None
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
        try:
            return moment.replace(tzinfo=tz, microsecond=0).astimezone(timezone.utc)
        except (OverflowError, ValueError):
            return None  # e.g. .NET's "0001-01-01T00:00:00" placeholder east of UTC
    return None


def _from_struct(value: object) -> datetime | None:
    try:
        return datetime.fromtimestamp(calendar.timegm(value), tz=timezone.utc).replace(microsecond=0)
    except (OverflowError, TypeError, ValueError):
        return None


def _from_wall_clock(value: object, tz: tzinfo) -> datetime | None:
    """feedparser's reading of a date it took as UTC, reinterpreted as wall-clock time in tz."""
    try:
        return datetime(*value[:6], tzinfo=tz).astimezone(timezone.utc)
    except (OverflowError, TypeError, ValueError):
        return None


def entry_published(entry: dict, now: datetime, tz: tzinfo = timezone.utc) -> datetime | None:
    """Publication time: published, else updated, else created (never a later field over an earlier one)."""
    for key in ("published", "updated", "created"):
        raw = dict.get(entry, key)  # dict.get skips feedparser's deprecated updated->published aliasing
        raw = raw.strip() if isinstance(raw, str) else ""
        parsed = dict.get(entry, f"{key}_parsed")
        named = _NAMED_ZONE.search(raw)
        if named:
            zone = NAMED_ZONES[named.group(1)]
            readings = [parse_loose_date(raw[: named.start()], zone), _from_wall_clock(parsed, zone)]
        elif raw and not _HAS_ZONE.search(raw):
            # feedparser reads a zone-less date as UTC; use the source's own zone instead.
            readings = [parse_loose_date(raw, tz), _from_wall_clock(parsed, tz)]
        else:
            readings = [_from_struct(parsed)]
        for moment in readings:
            if moment and _plausible(moment, now):
                return moment
    return None


def _excluded(title: str, source: Source) -> bool:
    return any(pattern.search(title) for pattern in source.exclude_title)


def _entry(raw: dict, base: str, source: Source, settings: Settings, now: datetime) -> Entry | None:
    url = entry_link(raw, base)
    if not url:
        return None
    # A plain-text title is already decoded; parsing it as HTML would eat "<script>" mentions.
    plain = (raw.get("title_detail") or {}).get("type") == "text/plain"
    title = clean_title(raw.get("title"), plain=plain)
    if title and _excluded(title, source):
        return None
    summary = make_summary(raw, source.summary_from, title, settings.summary_max_chars)
    if not title:
        if not summary:
            return None
        title = truncate(summary, 120)
        if _excluded(title, source):  # an untitled "Sponsored: …" item
            return None
    return Entry(item_id(url), url, title, summary, entry_published(raw, now, source.tz))


# A numeric character reference, also in its escaped-HTML form (&amp;#...;).
_CHARREF = re.compile(rb"&(amp;)?#(?:[xX]([0-9a-fA-F]+)|([0-9]+));")
_MAX_CODE_POINT = 0x10FFFF


def _charref_code(match: re.Match) -> int:
    """The code point a reference names, or -1 when it is too long to be one."""
    hex_digits, decimal = match.group(2), match.group(3)
    digits = hex_digits or decimal
    if len(digits.lstrip(b"0")) > 8:
        return -1
    return int(digits, 16 if hex_digits else 10)


def _invalid_code(code: int) -> bool:
    return code < 0 or code > _MAX_CODE_POINT or 0xD800 <= code <= 0xDFFF


def fix_charrefs(content: bytes) -> bytes:
    """Repair numeric character references that feedparser crashes on (and so fails the whole feed).

    Older Java and .NET escapers write an emoji as a UTF-16 surrogate pair, "&#55357;&#56960;":
    such a pair becomes one reference to the real code point. A lone surrogate, or a number past
    U+10FFFF, becomes U+FFFD. Valid references are left exactly as they are.
    """
    if b"#" not in content:
        return content
    matches = list(_CHARREF.finditer(content))
    out: list[bytes] = []
    pos = i = 0
    while i < len(matches):
        match = matches[i]
        code = _charref_code(match)
        if not _invalid_code(code):
            i += 1
            continue
        prefix = match.group(1) or b""
        end = match.end()
        following = matches[i + 1] if i + 1 < len(matches) else None
        low = _charref_code(following) if following else -1
        if (
            0xD800 <= code <= 0xDBFF
            and following is not None
            and following.start() == end
            and (following.group(1) or b"") == prefix
            and 0xDC00 <= low <= 0xDFFF
        ):
            code = 0x10000 + ((code - 0xD800) << 10) + (low - 0xDC00)
            end = following.end()
            i += 2
        else:
            code = 0xFFFD
            i += 1
        out.append(content[pos : match.start()])
        out.append(b"&" + prefix + b"#x%X;" % code)
        pos = end
    if not out:
        return content
    out.append(content[pos:])
    return b"".join(out)


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
    parsed = feedparser.parse(io.BytesIO(fix_charrefs(content)), response_headers=headers)
    if not parsed.entries:
        if not parsed.get("version"):
            problem = parsed.get("bozo_exception")
            detail = f" ({type(problem).__name__})" if problem else ""
            raise FeedParseError(f"not an RSS/Atom feed{detail}")
        return []

    base = parsed.feed.get("link")
    if not is_http_url(base):
        base = source.site  # a broken, relative or non-http channel <link> must not discard every entry
    entries: list[Entry] = []
    seen: set[str] = set()
    for raw in parsed.entries:
        try:
            entry = _entry(raw, base, source, settings, now)
        except (ValueError, OverflowError):
            continue  # e.g. a malformed URL or date; one bad entry must not sink the whole feed
        if entry is None or entry.id in seen:
            continue
        seen.add(entry.id)
        entries.append(entry)

    # Newest dated entries first; undated ones keep their feed order after them.
    dated = sorted((e for e in entries if e.published), key=lambda e: e.published, reverse=True)
    undated = [e for e in entries if not e.published]
    return (dated + undated)[: settings.max_items_per_source]
