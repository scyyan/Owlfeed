from datetime import datetime, timezone

import pytest

from owlfeed.config import Settings
from owlfeed.parse import FeedParseError, clean_link, item_id, parse_feed

from .conftest import NOW, feed_bytes, make_source


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


def test_clean_link_strips_only_tracking_parameters():
    assert clean_link("https://x.example/a?utm_source=rss&id=5&fbclid=abc") == "https://x.example/a?id=5"
    untouched = "https://x.example/a?b=1&c=hello%20world#frag"
    assert clean_link(untouched) == untouched


def test_item_id_ignores_scheme_case_and_fragment():
    assert item_id("https://Example.com/a") == item_id("http://example.com/a#top")
    assert item_id("https://example.com/a") != item_id("https://example.com/b")
