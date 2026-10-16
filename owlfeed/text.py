"""Turn feed HTML into clean titles and short plain-text summaries."""

from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser

BLOCK_TAGS = frozenset(
    "address article aside blockquote br dd div dl dt figure footer h1 h2 h3 h4 h5 h6 "
    "header hr li main nav ol p pre section table tbody td th tr ul".split()
)
SKIP_TAGS = frozenset(
    "button figcaption form iframe noscript object script select style svg template".split()
)

# Summaries shorter than this are treated as teasers and the next candidate is tried.
MIN_USEFUL_CHARS = 40
# A short paragraph without closing punctuation is treated as a heading ("Key Takeaways").
HEADING_MAX_CHARS = 40

_WHITESPACE = re.compile(r"\s+")
_LEFTOVER_ENTITY = re.compile(r"&(?:#\d{1,7}|#x[0-9a-fA-F]{1,6}|[a-zA-Z]{2,8});")
_TAG_LIKE = re.compile(r"<[a-zA-Z/!][^>]*>")
_SENTENCE_END = re.compile(r"[.!?…][\"'”’)\]]?(?=\s)")
_TERMINAL = re.compile(r"[.!?…:;\"'”’)\]]$")

# Whole paragraphs that are never part of an article's summary.
_JUNK_PARAGRAPH = re.compile(
    r"^(?:"
    r"sign up\b|subscribe\b|click here\b|read more\b|continue reading\b|keep reading\b"
    r"|the (?:post|article) .+ (?:appeared|was published) first on\b"
    r"|this (?:article|story|post) (?:was )?(?:originally|first) (?:appeared|published)\b"
    r"|\(c\)\s|©|copyright\b|creative commons\b"
    r"|categories:|tags:|filed under\b"
    r"|view csaf\b"
    r"|for the latest discoveries in cyber research\b"
    r"|(?:check out our (?:products|services)|want a demo|contact us (?:today|for)|request a demo|book a demo)\b"
    r"|the dfir report offerings\b"
    r")",
    re.IGNORECASE | re.DOTALL,
)

# Boilerplate that appears inside running text.
_INLINE_BOILERPLATE = [
    re.compile(r"\s*The (?:post|article) .{1,400}? (?:appeared|was published) first on .{1,200}$", re.I | re.S),
    re.compile(r"\s*This (?:article|story|post) (?:was )?(?:originally|first) (?:appeared|published) (?:on|in|at) .{0,200}$", re.I | re.S),
    re.compile(
        r"\s*(?:Continue reading|Keep reading|Read more|Read the (?:full|rest of the|complete) "
        r"(?:story|article|post|report|analysis)|Click here to read more)\b.{0,200}$",
        re.I | re.S,
    ),
    re.compile(r"\s*\(more…\)\s*$", re.I),
    re.compile(r"\s*Categories: .{0,200}?(?:Tags: .{0,300})?$", re.S),
    re.compile(r"^View CSAF\s+(?:Summary\s+)?", re.I),
]
_BRACKET_ELLIPSIS = re.compile(r"\s*\[\s*(?:…|\.\.\.)\s*\]")
# "…sentence.…" -> "…sentence." (some feeds append an ellipsis to complete sentences)
_PUNCTUATED_ELLIPSIS = re.compile(r"([.!?])\s*…$")


class _ParagraphExtractor(HTMLParser):
    """Collects text, starting a new paragraph at every block-level boundary."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.paragraphs: list[str] = []
        self._buffer: list[str] = []
        self._skip_depth = 0

    def _flush(self) -> None:
        text = collapse_whitespace("".join(self._buffer))
        if text:
            self.paragraphs.append(text)
        self._buffer = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in SKIP_TAGS:
            self._skip_depth += 1
        elif tag in BLOCK_TAGS:
            self._flush()

    def handle_startendtag(self, tag: str, attrs: list) -> None:
        if tag in BLOCK_TAGS:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in BLOCK_TAGS:
            self._flush()

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self._buffer.append(data)

    def close(self) -> None:
        super().close()
        self._flush()


def collapse_whitespace(text: str) -> str:
    return _WHITESPACE.sub(" ", text.replace(" ", " ")).strip()


def _parse_paragraphs(value: str) -> list[str]:
    parser = _ParagraphExtractor()
    parser.feed(value)
    parser.close()
    # Some feeds double-escape entities (e.g. "&amp;#8217;"); decode the leftovers once more.
    return [_LEFTOVER_ENTITY.sub(lambda m: unescape(m.group(0)), p) for p in parser.paragraphs]


def html_to_paragraphs(value: object) -> list[str]:
    """Split feed HTML into plain-text paragraphs (tags stripped, entities decoded)."""
    if not isinstance(value, str) or not value.strip():
        return []
    if "<" not in value and "&" not in value:
        return [collapse_whitespace(value)]
    paragraphs = []
    for paragraph in _parse_paragraphs(value):
        # Double-escaped HTML ("&lt;p&gt;") only becomes markup after the first pass.
        paragraphs.extend(_parse_paragraphs(paragraph) if _TAG_LIKE.search(paragraph) else [paragraph])
    return [p for p in paragraphs if p]


def html_to_text(value: object) -> str:
    """Strip tags, decode entities and collapse whitespace into one line."""
    return " ".join(html_to_paragraphs(value))


def clean_title(value: object, max_chars: int = 300) -> str:
    return truncate(html_to_text(value), max_chars)


def _is_heading(paragraph: str) -> bool:
    return len(paragraph) <= HEADING_MAX_CHARS and not _TERMINAL.search(paragraph)


def summary_text(value: object, title: str = "") -> str:
    """Readable summary text: junk paragraphs and headings dropped, paragraphs joined as sentences."""
    kept = [p for p in html_to_paragraphs(value) if not _JUNK_PARAGRAPH.match(p)]
    body = [p for p in kept if not _is_heading(p)] or kept
    sentences = [p if i == len(body) - 1 or _TERMINAL.search(p) else p + "." for i, p in enumerate(body)]
    return strip_boilerplate(" ".join(sentences), title)


def strip_boilerplate(text: str, title: str = "") -> str:
    text = _BRACKET_ELLIPSIS.sub("…", text)
    for pattern in _INLINE_BOILERPLATE:
        text = pattern.sub("", text)
    text = _PUNCTUATED_ELLIPSIS.sub(r"\1", text.strip())
    if title:
        if text.casefold() == title.casefold():
            return ""
        # Drop a repeated headline at the start, but only as a whole phrase ("T" must not eat "The").
        repeated = re.match(re.escape(title) + r"(?!\w)", text, re.IGNORECASE)
        if repeated:
            rest = text[repeated.end():].lstrip(" \t-–—:|.")
            if len(rest) >= MIN_USEFUL_CHARS // 2:
                text = rest
    return text.strip()


def truncate(text: str, max_chars: int) -> str:
    """Shorten to max_chars, preferring a sentence end, else a word boundary plus an ellipsis."""
    if len(text) <= max_chars:
        return text
    window = text[: max_chars + 1]
    cut = 0
    for match in _SENTENCE_END.finditer(window):
        if max_chars // 2 <= match.end() <= max_chars:
            cut = match.end()
    if cut:
        return text[:cut].rstrip()
    space = window.rfind(" ", 0, max_chars)
    if space < max_chars // 2:
        space = max_chars - 1
    return text[:space].rstrip(" ,;:-–—(") + "…"


def _candidates(entry: dict, mode: str) -> list[str]:
    description = entry.get("summary") or ""
    contents = [c.get("value") or "" for c in entry.get("content") or [] if isinstance(c, dict)]
    content = max(contents, key=len) if contents else ""
    if mode == "description":
        return [description]
    if mode == "content":
        return [content, description]
    return [description, content]


def make_summary(entry: dict, mode: str, title: str, max_chars: int) -> str:
    """Pick the most useful summary text a feed entry offers and trim it to max_chars."""
    fallback = ""
    for raw in _candidates(entry, mode):
        text = summary_text(raw, title)
        if len(text) >= MIN_USEFUL_CHARS:
            return truncate(text, max_chars)
        if len(text) > len(fallback):
            fallback = text
    return truncate(fallback, max_chars)
