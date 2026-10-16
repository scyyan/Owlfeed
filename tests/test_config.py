import re

import pytest

from owlfeed.config import ConfigError, load_config, parse_config


def source(**overrides):
    base = {
        "id": "example",
        "name": "Example",
        "feed": "https://example.com/feed",
        "site": "https://example.com/",
        "category": "Cyber",
        "group": "Security news",
    }
    base.update(overrides)
    return base


def test_valid_config_with_defaults():
    config = parse_config({"sources": [source(), source(id="other", enabled=False, exclude_title=["^Deal:"])]})
    assert config.settings.retention_days == 7
    assert [s.id for s in config.enabled_sources] == ["example"]
    other = config.sources[1]
    assert other.exclude_title[0].search("deal: cheap stuff")  # case-insensitive


@pytest.mark.parametrize(
    "bad, message",
    [
        (source(id="Bad Id"), "lowercase"),
        (source(feed="ftp://example.com/feed"), "'feed' must be an http(s) URL"),
        (source(site=None), "'site' must be an http(s) URL"),
        (source(name=""), "'name' is required"),
        (source(enabled="yes"), "'enabled' must be true or false"),
        (source(summary_from="body"), "summary_from"),
        (source(exclude_title=["("]), "invalid exclude_title"),
        (source(exclude_title="Deal"), "list of regular expressions"),
        (source(timezone="Mars/Olympus"), "time zone name"),
        (source(category="cyber"), "category must be one of Cyber, Geopolitics (got 'cyber')"),
        (source(group="News"), "group for Cyber must be one of"),
        (source(feed="http://example.com/feed"), "'feed' must use https://"),
        (source(feed="https://[broken-ipv6/feed"), "'feed' must be an http(s) URL"),
    ],
)
def test_invalid_sources(bad, message):
    with pytest.raises(ConfigError, match=re.escape(message)):
        parse_config({"sources": [bad]})


def test_duplicate_ids_rejected():
    with pytest.raises(ConfigError, match="duplicate"):
        parse_config({"sources": [source(), source()]})


@pytest.mark.parametrize("settings", [{"retention_days": 0}, {"retention_days": "7"}, {"summary_max_chars": 10}, {"max_items_per_source": True}])
def test_invalid_settings(settings):
    with pytest.raises(ConfigError, match="settings"):
        parse_config({"settings": settings, "sources": [source()]})


def test_missing_or_malformed_file(tmp_path):
    with pytest.raises(ConfigError, match="cannot read"):
        load_config(tmp_path / "nope.yml")
    bad = tmp_path / "bad.yml"
    bad.write_text("sources: [unclosed", encoding="utf-8")
    with pytest.raises(ConfigError, match="not valid YAML"):
        load_config(bad)
    empty = tmp_path / "empty.yml"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(empty)


def test_custom_categories():
    config = parse_config({
        "settings": {"categories": {"Defense": ["Industry"]}},
        "sources": [source(category="Defense", group="Industry")],
    })
    assert dict(config.categories) == {"Defense": ("Industry",)}
    with pytest.raises(ConfigError, match="list of group names"):
        parse_config({"settings": {"categories": {"Defense": "Industry"}}, "sources": [source()]})
