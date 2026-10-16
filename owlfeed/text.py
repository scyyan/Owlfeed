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

_WHITESPACE = re.compile(r"\s+")
_LEFTOVER_ENTITY = re.compile(r"&(?:#\d{1,7}|#x[0-9a-fA-F]{1,6}|[a-zA-Z]{2,8});")
_SENTENCE_END = re.compile(r"[.!?…][\"'”’)\]]?(?=\s)")

_BOILERPLATE = [
    # WordPress: "The post <title> appeared first on <site>."
    re.compile(r"\s*The (?:post|article) .{1,400}? (?:appeared|was published) first on .{1,200}$", re.I | re.S),
    re.compile(r"\s*This (?:article|story|post) (?:was )?originally (?:appeared|published) (?:on|in|at) .{0,200}$", re.I | re.S),
    re.compile(
        r"\s*(?:Continue reading|Keep reading|Read more|Read the (?:full|rest of the|complete) "
        r"(?:story|article|post|report|analysis)|Click here to read more)\b.{0,200}$",
        re.I | re.S,
    ),
    re.compile(r"\s*\(more…\)\s*$", re.I),
]
_BRACKET_ELLIPSIS = re.compile(r"\s*\[\s*(?:…|\.\.\.)\s*\]")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in SKIP_TAGS:
            self._skip_depth += 1
        elif tag in BLOCK_TAGS:
            self.parts.append(" ")

    def handle_startendtag(self, tag: str, attrs: list) -> None:
        if tag in BLOCK_TAGS:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in BLOCK_TAGS:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)


def collapse_whitespace(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def html_to_text(value: object) -> str:
    """Strip tags, decode entities and collapse whitespace."""
    if not isinstance(value, str) or not value:
        return ""
    if "<" in value or "&" in value:
        parser = _TextExtractor()
        parser.feed(value)
        parser.close()
        value = "".join(parser.parts)
        # Some feeds double-escape entities (e.g. "&amp;#8217;"); decode the leftovers once more.
        value = _LEFTOVER_ENTITY.sub(lambda m: unescape(m.group(0)), value)
    return collapse_whitespace(value.replace(" ", " "))


def clean_title(value: object, max_chars: int = 300) -> str:
    return truncate(html_to_text(value), max_chars)


def strip_boilerplate(text: str, title: str = "") -> str:
    text = _BRACKET_ELLIPSIS.sub("…", text)
    for pattern in _BOILERPLATE:
        text = pattern.sub("", text)
    text = text.strip()
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
        text = strip_boilerplate(html_to_text(raw), title)
        if len(text) >= MIN_USEFUL_CHARS:
            return truncate(text, max_chars)
        if len(text) > len(fallback):
            fallback = text
    return truncate(fallback, max_chars)
