"""Load and validate sources.yml."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import timedelta, timezone, tzinfo
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

# How far in the future a date may be (clock skew) before it is treated as wrong.
FUTURE_TOLERANCE = timedelta(minutes=10)
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
SUMMARY_MODES = ("auto", "description", "content")
SOURCE_KEYS = frozenset(
    {"id", "name", "feed", "site", "category", "group", "enabled", "summary_from", "exclude_title", "timezone"}
)
# Used when sources.yml has no settings.categories: category -> its sidebar groups.
DEFAULT_CATEGORIES = {
    "Cyber": ("Government & CERT", "Threat research", "Security news"),
    "Geopolitics": ("Analysis & investigations", "World news"),
}


class ConfigError(ValueError):
    """Raised when sources.yml is missing or malformed."""


@dataclass(frozen=True)
class Settings:
    retention_days: int = 7
    max_items_per_source: int = 50
    summary_max_chars: int = 320


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    feed: str
    site: str
    category: str
    group: str
    enabled: bool = True
    summary_from: str = "auto"
    exclude_title: tuple[re.Pattern, ...] = field(default=(), compare=False)
    # Applied only to dates that carry no time zone of their own.
    tz: tzinfo = timezone.utc


@dataclass(frozen=True)
class Config:
    settings: Settings
    sources: tuple[Source, ...]
    categories: tuple[tuple[str, tuple[str, ...]], ...] = tuple(DEFAULT_CATEGORIES.items())

    @property
    def enabled_sources(self) -> tuple[Source, ...]:
        return tuple(s for s in self.sources if s.enabled)


def is_http_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = urlparse(value.strip())
    except ValueError:  # e.g. "https://[broken-ipv6/"
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _int_setting(raw: dict, key: str, default: int, low: int, high: int) -> int:
    value = raw.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ConfigError(f"settings.{key} must be a whole number between {low} and {high}")
    return value


def _text_field(raw: dict, key: str, where: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{where}: '{key}' is required")
    return value.strip()


def _parse_categories(raw: object) -> dict[str, tuple[str, ...]]:
    if raw is None:
        return dict(DEFAULT_CATEGORIES)
    if not isinstance(raw, dict) or not raw:
        raise ConfigError("settings.categories must map each category to a list of groups")
    categories: dict[str, tuple[str, ...]] = {}
    for name, groups in raw.items():
        if not isinstance(name, str) or not name.strip():
            raise ConfigError("settings.categories: category names must be text")
        if not isinstance(groups, list) or not groups or not all(isinstance(g, str) and g.strip() for g in groups):
            raise ConfigError(f"settings.categories.{name} must be a list of group names")
        categories[name.strip()] = tuple(g.strip() for g in groups)
    return categories


def _parse_source(raw: object, index: int, categories: dict[str, tuple[str, ...]]) -> Source:
    where = f"sources[{index}]"
    if not isinstance(raw, dict):
        raise ConfigError(f"{where} must be a mapping")
    source_id = _text_field(raw, "id", where)
    where = f"source '{source_id}'"
    unknown = sorted(str(key) for key in set(raw) - SOURCE_KEYS)
    if unknown:
        raise ConfigError(f"{where}: unknown option(s) {', '.join(unknown)}")
    if not ID_PATTERN.match(source_id):
        raise ConfigError(f"{where}: id must be lowercase letters, digits and dashes")
    for key in ("feed", "site"):
        if not is_http_url(raw.get(key)):
            raise ConfigError(f"{where}: '{key}' must be an http(s) URL")
    if not raw["feed"].strip().lower().startswith("https://"):
        raise ConfigError(f"{where}: 'feed' must use https://")
    enabled = raw.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ConfigError(f"{where}: 'enabled' must be true or false")
    summary_from = raw.get("summary_from", "auto")
    if summary_from not in SUMMARY_MODES:
        raise ConfigError(f"{where}: 'summary_from' must be one of {', '.join(SUMMARY_MODES)}")
    patterns = raw.get("exclude_title", [])
    if not isinstance(patterns, list) or not all(isinstance(p, str) for p in patterns):
        raise ConfigError(f"{where}: 'exclude_title' must be a list of regular expressions")
    try:
        compiled = tuple(re.compile(p, re.IGNORECASE) for p in patterns)
    except re.error as exc:
        raise ConfigError(f"{where}: invalid exclude_title pattern: {exc}") from exc
    category, group = _text_field(raw, "category", where), _text_field(raw, "group", where)
    if category not in categories:
        raise ConfigError(f"{where}: category must be one of {', '.join(categories)} (got {category!r})")
    if group not in categories[category]:
        raise ConfigError(f"{where}: group for {category} must be one of {', '.join(categories[category])} (got {group!r})")
    zone_name = raw.get("timezone", "UTC")
    try:
        zone = ZoneInfo(zone_name) if isinstance(zone_name, str) else None
    except (ZoneInfoNotFoundError, ValueError):
        zone = None
    if zone is None:
        raise ConfigError(f"{where}: 'timezone' must be a time zone name such as Europe/Brussels")
    return Source(
        id=source_id,
        name=_text_field(raw, "name", where),
        feed=raw["feed"].strip(),
        site=raw["site"].strip(),
        category=category,
        group=group,
        enabled=enabled,
        summary_from=summary_from,
        exclude_title=compiled,
        tz=zone,
    )


def parse_config(data: object) -> Config:
    if not isinstance(data, dict):
        raise ConfigError("sources.yml must contain 'settings' and 'sources'")
    raw_settings = data.get("settings") or {}
    if not isinstance(raw_settings, dict):
        raise ConfigError("settings must be a mapping")
    settings = Settings(
        retention_days=_int_setting(raw_settings, "retention_days", 7, 1, 90),
        max_items_per_source=_int_setting(raw_settings, "max_items_per_source", 50, 1, 500),
        summary_max_chars=_int_setting(raw_settings, "summary_max_chars", 320, 80, 2000),
    )
    categories = _parse_categories(raw_settings.get("categories"))
    raw_sources = data.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise ConfigError("sources must be a non-empty list")
    sources = tuple(_parse_source(raw, i, categories) for i, raw in enumerate(raw_sources))
    seen: set[str] = set()
    for source in sources:
        if source.id in seen:
            raise ConfigError(f"duplicate source id '{source.id}'")
        seen.add(source.id)
    return Config(settings=settings, sources=sources, categories=tuple(categories.items()))


def load_config(path: str | Path) -> Config:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from exc
    return parse_config(data)
