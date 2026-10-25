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
# Real markup that survived a first decoding pass, i.e. double-escaped HTML ("&lt;p&gt;…&lt;/p&gt;").
# Only common content tags count, and a paragraph is parsed again only when it opens with such a tag
# (or a complete comment) or closes one. Prose that names a tag ("inject a <pre> block",
# "an <!-- HTML comment -->", "How <script> tags hide malware") keeps its words.
_CONTENT_TAGS = (
    r"(?:p|div|span|a|em|strong|b|i|u|ul|ol|li|h[1-6]|br|hr|figure|img|blockquote|table|tbody|tr|td|th"
    r"|section|article|aside|header|footer|main|nav|pre|dl|dt|dd)"
)
_ESCAPED_OPENING = re.compile(rf"<!--.*?-->|<{_CONTENT_TAGS}(?:\s[^<>]*)?/?>", re.IGNORECASE | re.DOTALL)
_ESCAPED_CLOSING = re.compile(rf"</{_CONTENT_TAGS}\s*>", re.IGNORECASE)
# Void markup no one writes in prose, removed on its own (other tags the text names keep their words):
# line breaks glued to a word or the end of a sentence, quote or bracket ("Friday.<br /><br />The",
# "possible.”<br />", "(CVSS 9.8)<br />"), a 1x1 tracking pixel, and a WordPress comment standing
# between sentences. "converts newlines to <br>, but", 'such as "<br>"' and '("<br>", "<hr>")' are prose.
_BREAK_RUN = re.compile(r"<br\s*/?>(?:\s*<br\s*/?>)*", re.IGNORECASE)
# What a break run is glued to on its left: a word, a sentence end, a closing bracket or curly quote,
# or a straight quote that closes one of those.
_GLUED_BEFORE_BREAK = re.compile(r"(?:[\w.!?:;…%)\]”’]|[\w.!?…%)\]][\"'])$")
# Once one break is plainly markup, every break in that text is (nl2br output: "Monday. <br />\nCitizens").
_ANY_BREAKS = re.compile(r"(?:<br\s*/?>\s*)+", re.IGNORECASE)
_STRAY_COMMENT = re.compile(
    r"(?:^|(?<=[.!?\"'”’)>]))\s*<!--\s*(?:more|/?wp:)[^<>]*-->\s*(?=$|[A-Z<])", re.IGNORECASE
)
_IMAGE_TAG = re.compile(r"<img\s[^<>]*>", re.IGNORECASE)
_HTTP_SRC = re.compile(r"""\bsrc\s*=\s*["']https?://""", re.IGNORECASE)
_QUOTED_SRC = re.compile(r"""\bsrc\s*=\s*["']""", re.IGNORECASE)
_PIXEL_SIZE = re.compile(r"""\b(?:width|height)\s*=\s*["']?[01](?![\d.])""", re.IGNORECASE)
_EVENT_HANDLER = re.compile(r"\son[a-z]+\s*=", re.IGNORECASE)
# Removed whole before the second pass: a caption, script or style that really closes, taken from its
# nearest opening tag, so a mentioned "<script>" earlier in the text cannot hide the words after it.
_CLOSED_SKIP = re.compile(rf"<({'|'.join(sorted(SKIP_TAGS))})\b[^<>]*>(?:(?!<\1\b).)*?</\1\s*>", re.IGNORECASE | re.DOTALL)
# Decoded on the first pass, these can sit in front of the opening tag of double-escaped HTML.
_INVISIBLE_LEAD = "\xa0\u200b\ufeff "
_SENTENCE_END = re.compile(r"[.!?…][\"'”’)\]]?(?=\s)")
# A period after these is not a sentence end: "U.S.", "J. Smith", "Gen. Smith", "Oct. 12", "3 a.m.".
# A lone capital counts only when it is not part of a name like "AT&T" or "APT X" ("CEO J. Smith" does).
_ABBREVIATION = re.compile(
    r"(?:(?<![&\w])(?<!\bAPT )[A-Z]|\b(?:Mr|Mrs|Ms|Dr|Prof|St|Mt|Inc|Ltd|Co|Corp|Gen|Gov|Sen|Rep|Lt|Col|Sgt|Capt"
    r"|Adm|Maj|Brig|Dept|Jr|Sr|No|vs|etc|approx|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept?|Oct|Nov|Dec|e\.g|i\.e|a\.m|p\.m))\.$"
)
# "3 a.m. local time", "Smith et al. found": a short, dotted or listed lowercase word before the period.
_LOWERCASE_ABBREVIATION = re.compile(r"(?:\b[a-z]{1,3}|\.[a-z]|\b(?:incl|excl|approx|govt|dept|esp|resp|misc))\.$")
_TERMINAL = re.compile(r"[.!?…:;\"'”’)\]]$")

# Whole (short) paragraphs that are never part of an article's summary.
JUNK_MAX_CHARS = 300
_JUNK_PARAGRAPH = re.compile(
    r"^(?:"
    r"sign up (?:for|to|now|here|today)\b|subscribe (?:to|now|for|here|today)\b|click here (?:to|for)\b"
    # The Guardian: "Get our breaking news email, free app or daily news podcast".
    r"|get our (?:[\w'’-]+ ){1,4}(?:email|newsletter)s?\b"
    r"|read more\b|continue reading\b|keep reading\b"
    r"|the (?:post|article) .+ (?:appeared|was published) first on\b"
    r"|this (?:article|story|post) (?:was )?(?:originally|first) (?:appeared|published)\b"
    r"|\(c\)\s|©|copyright\s*(?:©|\(c\)|\d{4})|creative commons\b"
    r"|categories:|tags:|filed under:"
    r"|view csaf\b|written by:"
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
    # Only as a trailing call to action: at the start or right after a sentence end, never mid-word
    # ("can spread more") or mid-sentence.
    re.compile(
        r"(?:^|(?<=[.!?…\]»)])|(?<=[.!?…][\"'”’]))\s*(?:Continue reading|Keep reading|Read more|Read the (?:full|rest of the|complete) "
        r"(?:story|article|post|report|analysis)|Click here to read more)\b.{0,200}$",
        re.I | re.S,
    ),
    # A capitalised call to action closing an excerpt mid-sentence ("…the servers Read more").
    # Case-sensitive, so ordinary prose such as "can spread more" is never touched.
    re.compile(
        r"\s*\[?\b(?:Continue reading|Keep reading|Read [Mm]ore|Read the (?:full|rest of the|complete) "
        r"(?:story|article|post|report|analysis))\W*$"
    ),
    re.compile(r"\s*\(more…\)\s*$", re.I),
    re.compile(r"\s*Categories: .{0,200}?(?:Tags: .{0,300})?$", re.S),
    re.compile(r"^View CSAF\s+(?:Summary\s+)?", re.I),
    # Prefer ending at the closing call-to-action; fall back to the "Get in Touch" heading.
    re.compile(r"The DFIR Report Offerings\b(?:.{0,300}?pricing or a demo!|.{0,200}?Get in Touch)\s*", re.S),
    # Run after the marketing block is gone: it can sit between two such headings.
    re.compile(r"^(?:(?:Key Takeaways|Case Summary)\s+)+"),
]
# SANS ISC appends the diary date to titles: "Title, (Wed, Oct 14th)".
_TITLE_DATE_SUFFIX = re.compile(r",?\s*\((?:Mon|Tue|Wed|Thu|Fri|Sat|Sun), [A-Z][a-z]{2} \d{1,2}(?:st|nd|rd|th)\)$")
_BRACKET_ELLIPSIS = re.compile(r"\s*\[\s*(?:…|\.\.\.)\s*\]")
# "…sentence.…" -> "…sentence." (some feeds append an ellipsis to complete sentences)
_PUNCTUATED_ELLIPSIS = re.compile(r"([.!?])\s*…$")


def _has_stray_break(text: str) -> bool:
    """A line break glued to a word or a sentence end on either side, i.e. markup rather than a mention."""
    for run in _BREAK_RUN.finditer(text):  # one pass, so long runs of breaks stay cheap
        after = text[run.end() : run.end() + 1]
        if _GLUED_BEFORE_BREAK.search(text[max(0, run.start() - 2) : run.start()]) or after.isalnum() or after == "_":
            return True
    return False


def _is_tracking_pixel(tag: str) -> bool:
    return bool(_HTTP_SRC.search(tag) and _PIXEL_SIZE.search(tag))


def _is_stray_title_image(tag: str) -> bool:
    """An image with a quoted source, unless it is the payload the headline is about (onerror=…)."""
    return bool(_QUOTED_SRC.search(tag) and not _EVENT_HANDLER.search(tag))


def _drop_images(text: str, stray) -> str:
    return _IMAGE_TAG.sub(lambda m: " " if stray(m.group(0)) else m.group(0), text)


class _ParagraphExtractor(HTMLParser):
    """Collects text, starting a new paragraph at every block-level boundary."""

    def __init__(self, skip_tags: frozenset[str] = SKIP_TAGS, raw_text: bool = True) -> None:
        super().__init__(convert_charrefs=True)
        self.paragraphs: list[str] = []
        self._buffer: list[str] = []
        self._skip_depth = 0
        self._skip_tags = skip_tags
        if not raw_text:
            # Treat <script>/<style> (and, on newer Pythons, <textarea>/<title>) as ordinary tags, not as
            # raw-text containers, so text after a mentioned "<script>" is still parsed normally.
            self.CDATA_CONTENT_ELEMENTS = ()
            self.RCDATA_CONTENT_ELEMENTS = ()

    def _flush(self) -> None:
        text = collapse_whitespace("".join(self._buffer))
        if text:
            self.paragraphs.append(text)
        self._buffer = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in self._skip_tags:
            self._skip_depth += 1
        elif tag in BLOCK_TAGS:
            self._flush()

    def handle_startendtag(self, tag: str, attrs: list) -> None:
        if tag in BLOCK_TAGS:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag in self._skip_tags:
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
    return _WHITESPACE.sub(" ", text).strip()  # \s also matches non-breaking spaces


def _parse_paragraphs(value: str, skip_tags: frozenset[str] = SKIP_TAGS, raw_text: bool = True) -> list[str]:
    parser = _ParagraphExtractor(skip_tags, raw_text)
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
        # Double-escaped HTML ("&lt;p&gt;") only becomes markup after the first pass. Captions, scripts,
        # styles and the like that really close are cut out first; then nothing is skipped, so prose that
        # mentions "<script>" next to real markup keeps the words after it.
        if _ESCAPED_OPENING.match(paragraph.lstrip(_INVISIBLE_LEAD)) or _ESCAPED_CLOSING.search(paragraph):
            paragraphs.extend(_parse_paragraphs(_CLOSED_SKIP.sub(" ", paragraph), frozenset(), raw_text=False))
        elif "<" in paragraph:
            cleaned = _STRAY_COMMENT.sub(" ", _drop_images(paragraph, _is_tracking_pixel))
            parts = _ANY_BREAKS.split(cleaned) if _has_stray_break(cleaned) else [cleaned]
            paragraphs.extend(p for p in map(collapse_whitespace, parts) if p)
        else:
            paragraphs.append(paragraph)
    return [p for p in paragraphs if p]


def html_to_text(value: object) -> str:
    """Strip tags, decode entities and collapse whitespace into one line."""
    return " ".join(html_to_paragraphs(value))


def clean_title(value: object, max_chars: int = 300, plain: bool = False) -> str:
    """plain=True for titles the feed marks as plain text: they are decoded already, not HTML."""
    if plain and isinstance(value, str):
        # Stray line breaks and images still show up in some plain titles; a tag the headline names
        # ("XSS via <img> tags", "<img src=x onerror=…>", "fixes <br>-handling flaw") stays.
        text = _drop_images(value, _is_stray_title_image)
        text = _ANY_BREAKS.sub(" ", text) if _has_stray_break(text) else text
        text = collapse_whitespace(_LEFTOVER_ENTITY.sub(lambda m: unescape(m.group(0)), text))
    else:
        text = html_to_text(value)
    return truncate(_TITLE_DATE_SUFFIX.sub("", text), max_chars)


def _is_heading(paragraph: str) -> bool:
    return len(paragraph) <= HEADING_MAX_CHARS and not _TERMINAL.search(paragraph)


def summary_text(value: object, title: str = "") -> str:
    """Readable summary text: junk paragraphs and headings dropped, paragraphs joined as sentences."""
    kept = [p for p in html_to_paragraphs(value) if not (len(p) <= JUNK_MAX_CHARS and _JUNK_PARAGRAPH.match(p))]
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
        if not max_chars // 2 <= match.end() <= max_chars:
            continue
        if _ABBREVIATION.search(text[: match.start() + 1]):
            continue
        if text[match.end():].lstrip()[:1].islower() and (
            text[match.start()] != "." or _LOWERCASE_ABBREVIATION.search(text[: match.start() + 1])
        ):
            # 'asks "Is this your parcel?" before…', "…et al. found": the sentence goes on
            # (but "…the flaw. iOS 18.1 fixes…" ends one).
            continue
        cut = match.end()
    if cut:
        return text[:cut].rstrip()
    space = window.rfind(" ", 0, max_chars)
    if space < max_chars // 2:
        space = max_chars - 1
    return text[:space].rstrip(" ,;:-–—(.") + "…"


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
