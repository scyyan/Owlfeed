"""The real sources.yml must load: the refresh rejects the same mistakes and keeps the last good dashboard."""

from owlfeed.config import load_config

from .conftest import ROOT


def test_sources_file_is_valid():
    config = load_config(ROOT / "sources.yml")
    assert config.enabled_sources, "at least one source must be enabled"
    # load_config already rejects sources outside the declared categories and groups, so new ones
    # can be added freely; this only flags a declared category that no enabled source uses.
    for category, _groups in config.categories:
        assert any(s.category == category for s in config.enabled_sources), f"no enabled source in {category}"
