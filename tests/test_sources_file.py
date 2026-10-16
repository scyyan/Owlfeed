"""Guards for the real sources.yml, so a bad edit fails CI instead of the live refresh."""

from owlfeed.config import load_config

from .conftest import ROOT

GROUPS = {
    "Cyber": {"Government & CERT", "Threat research", "Security news"},
    "Geopolitics": {"Analysis & investigations", "World news"},
}


def test_sources_file_is_valid():
    config = load_config(ROOT / "sources.yml")
    assert config.enabled_sources, "at least one source must be enabled"
    for source in config.sources:
        assert source.category in GROUPS, f"{source.id}: unknown category {source.category!r}"
        assert source.group in GROUPS[source.category], f"{source.id}: unknown group {source.group!r}"
        assert source.feed.startswith("https://"), f"{source.id}: use an https feed URL"
