"""The real sources.yml must load: the refresh rejects the same mistakes and keeps the last good dashboard."""

from owlfeed.config import load_config

from .conftest import ROOT


def test_sources_file_is_valid():
    config = load_config(ROOT / "sources.yml")
    assert config.enabled_sources, "at least one source must be enabled"
    assert dict(config.categories) == {
        "Cyber": ("Government & CERT", "Threat research", "Security news"),
        "Geopolitics": ("Analysis & investigations", "World news"),
    }
