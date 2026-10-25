from datetime import datetime, timezone

import pytest

from owlfeed.config import Settings
from owlfeed.parse import FeedParseError, clean_link, item_id, parse_feed, parse_loose_date

from .conftest import FEEDS, NOW, feed_bytes, make_source


def parse(name, settings=Settings(), **source_overrides):
    source = make_source("news", site="https://news.example.com/", **source_overrides)
    return parse_feed(feed_bytes(name), source, settings, NOW)


def by_title(entries):
    return {e.title: e for e in entries}


def test_wordpress_feed():
    entries = parse("wordpress.xml")
    assert [e.title for e in entries] == [
        "Ransomware crew targets ExampleVPN gateways",
        "Hackers’ new loader abuses signed drivers",
    ]
    first, second = entries
    assert first.url == "https://blog.example.com/2026/10/ransomware-examplevpn/"
    assert first.published == datetime(2026, 10, 15, 13, 2, tzinfo=timezone.utc)
    assert first.summary.startswith("Researchers observed a ransomware crew")
    assert "appeared first on" not in first.summary
    # The description is only a teaser, so the content is summarized instead (figure captions skipped).
    assert second.summary.startswith("A new loader abuses legitimately signed")
    assert "Figure 1" not in second.summary


def test_atom_feed_resolves_relative_links_and_uses_updated_date():
    entries = by_title(parse("atom.xml"))
    night_owl = entries["Inside Operation Night Owl"]
    assert night_owl.url == "https://research.example.org/posts/night-owl"
    assert night_owl.published == datetime(2026, 10, 15, 8, 15, tzinfo=timezone.utc)
    assert entries["Only an updated date"].published == datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)


def test_rdf_feed_converts_timezones_to_utc():
    (entry,) = parse("rdf.xml")
    assert entry.title == "Advisory 2026-001: Critical flaw in ExampleOS"
    assert entry.published == datetime(2026, 10, 15, 9, 45, tzinfo=timezone.utc)


def test_edge_cases():
    entries = parse("edge_cases.xml", exclude_title=[r"^Sponsored:"])
    titles = [e.title for e in entries]
    found = by_title(entries)

    assert found["No publication date"].published is None
    assert found["Dated far in the future"].published is None
    assert "Script link" not in titles  # no http(s) link anywhere
    assert "No publication date (duplicate)" not in titles  # same URL apart from the fragment
    assert not any(t.startswith("Sponsored") for t in titles)
    assert found["Feedburner original link"].url == "https://news.example.com/2026/10/original-article.html"
    assert found["Talks to resume next week"].summary == (
        "Officials say the talks will resume next week after a brief pause in negotiations."
    )
    assert found["Bold & brave"].summary == ""  # summary identical to the title
    assert found["Relative link"].url == "https://news.example.com/news/relative-link"
    assert found["Relative link"].summary.startswith("Script and style blocks never leak")
    long_summary = found["Very long description"].summary
    assert len(long_summary) <= 321 and long_summary.endswith("…")
    untitled = [e for e in entries if e.url == "https://news.example.com/untitled"]
    assert untitled and untitled[0].title.startswith("An untitled item still gets a headline")


def test_entries_are_newest_first_and_capped():
    entries = parse("edge_cases.xml", settings=Settings(max_items_per_source=3))
    assert len(entries) == 3
    dated = [e.published for e in parse("wordpress.xml")]
    assert dated == sorted(dated, reverse=True)


def test_summary_length_setting_is_respected():
    entries = parse("edge_cases.xml", settings=Settings(summary_max_chars=100))
    assert all(len(e.summary) <= 101 for e in entries)


def test_not_a_feed_raises():
    with pytest.raises(FeedParseError):
        parse("not_a_feed.html")


def test_empty_feed_is_valid():
    assert parse("empty.xml") == []


def test_loose_dates_and_source_timezones():
    feed = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>D</title><link>https://d.example/</link>
    <item><title>Drupal date</title><link>https://d.example/a</link><pubDate>Monday, October 12, 2026 - 21:44</pubDate></item>
    </channel></rss>"""
    source = make_source("drupal", timezone="Europe/Brussels")
    (entry,) = parse_feed(feed, source, Settings(), NOW)
    assert entry.published == datetime(2026, 10, 12, 19, 44, tzinfo=timezone.utc)  # CEST is UTC+2
    assert parse_loose_date("2026-10-15") == datetime(2026, 10, 15, tzinfo=timezone.utc)
    assert parse_loose_date("sometime soon") is None


def test_clean_link_strips_only_tracking_parameters():
    assert clean_link("https://x.example/a?utm_source=rss&id=5&fbclid=abc") == "https://x.example/a?id=5"
    assert clean_link("https://www.bbc.co.uk/news/articles/c1?at_medium=RSS&at_campaign=rss") == (
        "https://www.bbc.co.uk/news/articles/c1"
    )
    untouched = "https://x.example/a?b=1&c=hello%20world#frag"
    assert clean_link(untouched) == untouched


@pytest.mark.parametrize(
    "query",
    ["a=1;b=2", "q=caf%E9", "12345", "q=a%20b", "q=a+b&x=", "a=1&&b=2"],
)
def test_clean_link_keeps_the_rest_of_the_query_byte_for_byte(query):
    clean = f"https://x.example/a?{query}"
    assert clean_link(f"https://x.example/a?{query}&utm_source=rss") == clean
    assert clean_link(f"https://x.example/a?utm_source=rss&{query}#top") == f"{clean}#top"
    assert clean_link(f"https://x.example/a?UTM%5FMedium=x&{query}") == clean
    assert item_id(clean_link(f"{clean}&utm_source=rss")) == item_id(clean_link(clean))


def test_item_id_ignores_scheme_case_and_fragment():
    assert item_id("https://Example.com/a") == item_id("http://example.com/a#top")
    assert item_id("https://example.com/a") != item_id("https://example.com/b")


def test_response_body_is_never_treated_as_a_local_path():
    path_body = str(FEEDS / "wordpress.xml").encode()
    with pytest.raises(FeedParseError):
        parse_feed(path_body, make_source("evil"), Settings(), NOW)
    with pytest.raises(FeedParseError):
        parse_feed(b"/dev/zero", make_source("evil"), Settings(), NOW)


def test_one_malformed_entry_does_not_sink_the_feed():
    feed = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>M</title><link>https://m.example/</link>
    <item><title>Broken link</title><link>http://[not-an-ipv6/</link><pubDate>Wed, 15 Oct 2026 12:00:00 GMT</pubDate></item>
    <item><title>Fine</title><link>https://m.example/fine</link><pubDate>Wed, 15 Oct 2026 11:00:00 GMT</pubDate></item>
    </channel></rss>"""
    assert [e.title for e in parse_feed(feed, make_source("m"), Settings(), NOW)] == ["Fine"]


def _five_good_and(bad_item: bytes) -> bytes:
    good = b"".join(
        b"<item><title>Good %d</title><link>https://m.example/%d</link>"
        b"<pubDate>Wed, 14 Oct 2026 1%d:00:00 GMT</pubDate></item>" % (i, i, i)
        for i in range(5)
    )
    return (
        b'<?xml version="1.0"?><rss version="2.0"><channel><title>M</title><link>https://m.example/</link>'
        + good + bad_item + b"</channel></rss>"
    )


@pytest.mark.parametrize(
    "title, expected",
    [
        (b"Rocket &#55357;&#56960; launch", "Rocket \U0001F680 launch"),  # UTF-16 surrogate pair
        (b"Rocket &#xD83D;&#xDE80; launch", "Rocket \U0001F680 launch"),
        (b"Lone &#55357; surrogate", "Lone � surrogate"),
        (b"Too big &#x110000; here", "Too big � here"),
        (b"Way too big &#99999999999999999999; here", "Way too big � here"),
        (b"Valid &#233;t&#xE9; stays", "Valid été stays"),
    ],
)
def test_bad_character_references_do_not_sink_the_feed(title, expected):
    bad = b"<item><title>%s</title><link>https://m.example/bad</link></item>" % title
    entries = parse_feed(_five_good_and(bad), make_source("m"), Settings(), NOW)
    assert len(entries) == 6
    assert by_title(entries)[expected].url == "https://m.example/bad"


def test_escaped_surrogate_pairs_in_descriptions_are_repaired():
    bad = (
        b"<item><title>Emoji</title><link>https://m.example/bad</link>"
        b"<description>&lt;p&gt;Launch &amp;#55357;&amp;#56960; went well today.&lt;/p&gt;</description></item>"
    )
    entries = by_title(parse_feed(_five_good_and(bad), make_source("m"), Settings(), NOW))
    assert len(entries) == 6
    assert entries["Emoji"].summary == "Launch \U0001F680 went well today."


@pytest.mark.parametrize("date", [b"0001-01-01T00:00:00", b"Mon, 01 Jan 0001 00:00:00 CEST"])
def test_out_of_range_dates_do_not_sink_the_feed(date):
    bad = b"<item><title>Placeholder date</title><link>https://m.example/bad</link><pubDate>%s</pubDate></item>" % date
    entries = by_title(parse_feed(_five_good_and(bad), make_source("m", timezone="Europe/Brussels"), Settings(), NOW))
    assert len(entries) == 6
    assert entries["Placeholder date"].published is None


def test_zone_less_dates_use_the_source_timezone():
    feed = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>Z</title><link>https://z.example/</link>
    <item><title>ISO</title><link>https://z.example/a</link><pubDate>2026-10-12T21:44:00</pubDate></item>
    <item><title>RFC 822 without zone</title><link>https://z.example/b</link><pubDate>Mon, 12 Oct 2026 20:00:00</pubDate></item>
    <item><title>With offset</title><link>https://z.example/c</link><pubDate>Mon, 12 Oct 2026 20:00:00 +0000</pubDate></item>
    </channel></rss>"""
    found = by_title(parse_feed(feed, make_source("z", timezone="Europe/Brussels"), Settings(), NOW))
    assert found["ISO"].published == datetime(2026, 10, 12, 19, 44, tzinfo=timezone.utc)
    assert found["RFC 822 without zone"].published == datetime(2026, 10, 12, 18, 0, tzinfo=timezone.utc)
    assert found["With offset"].published == datetime(2026, 10, 12, 20, 0, tzinfo=timezone.utc)
    utc = by_title(parse_feed(feed, make_source("z"), Settings(), NOW))
    assert utc["RFC 822 without zone"].published == datetime(2026, 10, 12, 20, 0, tzinfo=timezone.utc)


def test_undated_entries_come_after_dated_ones():
    entries = parse("edge_cases.xml")
    first_undated = next(i for i, e in enumerate(entries) if e.published is None)
    assert all(e.published is None for e in entries[first_undated:])
    assert all(e.published is not None for e in entries[:first_undated])


def test_plain_text_titles_keep_tag_mentions():
    feed = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>T</title><link>https://t.example/</link>
    <item><title>How &lt;script&gt; tags hide malware in ads</title><link>https://t.example/1</link>
    <description>Researchers found injected loaders in ad networks across several regions.</description></item>
    </channel></rss>"""
    (entry,) = parse_feed(feed, make_source("t"), Settings(), NOW)
    assert entry.title == "How <script> tags hide malware in ads"
    assert entry.summary.startswith("Researchers found")


def test_plain_text_titles_drop_stray_line_breaks():
    feed = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>T</title><link>https://t.example/</link>
    <item><title>Breaking:&lt;br /&gt;Ransomware hits hospital chain</title><link>https://t.example/1</link></item>
    </channel></rss>"""
    (entry,) = parse_feed(feed, make_source("t"), Settings(), NOW)
    assert entry.title == "Breaking: Ransomware hits hospital chain"


def test_published_date_wins_over_a_zone_less_update():
    feed = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>A</title>
    <entry><title>Edited later</title><link href="https://a.example/1"/><id>x</id>
    <published>2026-10-01T09:00:00Z</published><updated>2026-10-15T12:00:00</updated></entry></feed>"""
    (entry,) = parse_feed(feed, make_source("a", timezone="Europe/Brussels"), Settings(), NOW)
    assert entry.published == datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)


def test_named_zone_abbreviations():
    feed = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>N</title><link>https://n.example/</link>
    <item><title>CEST</title><link>https://n.example/1</link><pubDate>Mon, 12 Oct 2026 21:44:00 CEST</pubDate></item>
    <item><title>Fractional</title><link>https://n.example/2</link><pubDate>2026-10-12T21:44:00.000</pubDate></item>
    </channel></rss>"""
    found = by_title(parse_feed(feed, make_source("n", timezone="Europe/Brussels"), Settings(), NOW))
    assert found["CEST"].published == datetime(2026, 10, 12, 19, 44, tzinfo=timezone.utc)
    assert found["Fractional"].published == datetime(2026, 10, 12, 19, 44, tzinfo=timezone.utc)


def test_broken_channel_link_falls_back_to_the_site():
    feed = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>B</title><link>https://[site-url]/</link>
    <item><title>Relative</title><link>/news/1</link></item></channel></rss>"""
    source = make_source("b", site="https://b.example/")
    (entry,) = parse_feed(feed, source, Settings(), NOW)
    assert entry.url == "https://b.example/news/1"


@pytest.mark.parametrize("channel_link", [b"/", b"b.example", b"ftp://b.example/", b""])
def test_unusable_channel_link_falls_back_to_the_site(channel_link):
    feed = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>B</title><link>%s</link>
    <item><title>Relative</title><link>/news/1</link></item></channel></rss>""" % channel_link
    (entry,) = parse_feed(feed, make_source("b", site="https://b.example/"), Settings(), NOW)
    assert entry.url == "https://b.example/news/1"


def test_an_opaque_guid_is_never_resolved_into_a_link():
    feed = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>G</title><link>https://g.example/news/</link>
    <item><title>Opaque guid</title><guid>abc-123</guid></item>
    <item><title>Permalink guid</title><guid>https://g.example/news/2</guid></item>
    <item><title>Real link</title><link>/news/3</link><guid>abc-125</guid></item>
    </channel></rss>"""
    found = by_title(parse_feed(feed, make_source("g"), Settings(), NOW))
    assert "Opaque guid" not in found
    assert found["Permalink guid"].url == "https://g.example/news/2"
    assert found["Real link"].url == "https://g.example/news/3"


def test_exclude_title_applies_to_a_title_taken_from_the_summary():
    feed = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>S</title><link>https://s.example/</link>
    <item><link>https://s.example/1</link><description>Sponsored: Join our webinar on cloud security next week.</description></item>
    <item><link>https://s.example/2</link><description>An untitled item about a real advisory gets a headline.</description></item>
    </channel></rss>"""
    entries = parse_feed(feed, make_source("s", exclude_title=[r"^Sponsored:"]), Settings(), NOW)
    assert [e.url for e in entries] == ["https://s.example/2"]


def test_dates_only_feedparser_reads_keep_their_zone():
    feed = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>N</title><link>https://n.example/</link>
    <item><title>Long month CEST</title><link>https://n.example/1</link><pubDate>Mon, 12 October 2026 21:44:00 CEST</pubDate></item>
    <item><title>Seven digits</title><link>https://n.example/2</link><pubDate>2026-10-12T21:44:00.1234567</pubDate></item>
    <item><title>Date only</title><link>https://n.example/3</link><pubDate>Mon, 12 Oct 2026</pubDate></item>
    <item><title>GMT</title><link>https://n.example/4</link><pubDate>Mon, 12 Oct 2026 21:44:00 GMT</pubDate></item>
    <item><title>Short offset</title><link>https://n.example/5</link><pubDate>2026-10-12T21:44:00+02</pubDate></item>
    <item><title>AST</title><link>https://n.example/6</link><pubDate>Mon, 12 Oct 2026 21:44:00 AST</pubDate></item>
    </channel></rss>"""
    found = by_title(parse_feed(feed, make_source("n", timezone="Europe/Brussels"), Settings(), NOW))
    assert found["Long month CEST"].published == datetime(2026, 10, 12, 19, 44, tzinfo=timezone.utc)
    assert found["Seven digits"].published == datetime(2026, 10, 12, 19, 44, tzinfo=timezone.utc)
    assert found["Date only"].published == datetime(2026, 10, 11, 22, 0, tzinfo=timezone.utc)
    assert found["GMT"].published == datetime(2026, 10, 12, 21, 44, tzinfo=timezone.utc)
    # Zones feedparser converts itself are still trusted.
    assert found["Short offset"].published == datetime(2026, 10, 12, 19, 44, tzinfo=timezone.utc)
    assert found["AST"].published == datetime(2026, 10, 13, 1, 44, tzinfo=timezone.utc)


def test_a_title_of_invisible_characters_falls_back_to_the_summary():
    feed = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>I</title><link>https://i.example/</link>
    <item><title>&#8203;&#65279;</title><link>https://i.example/1</link>
    <description>Researchers found a new loader in signed drivers this week.</description></item>
    </channel></rss>"""
    (entry,) = parse_feed(feed, make_source("i"), Settings(), NOW)
    assert entry.title == "Researchers found a new loader in signed drivers this week."
