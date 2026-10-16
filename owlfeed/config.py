"""Load and validate sources.yml."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import yaml

ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
SUMMARY_MODES = ("auto", "description", "content")


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


@dataclass(frozen=True)
class Config:
    settings: Settings
    sources: tuple[Source, ...]

    @property
    def enabled_sources(self) -> tuple[Source, ...]:
        return tuple(s for s in self.sources if s.enabled)


def is_http_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value.strip())
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


def _parse_source(raw: object, index: int) -> Source:
    where = f"sources[{index}]"
    if not isinstance(raw, dict):
        raise ConfigError(f"{where} must be a mapping")
    source_id = _text_field(raw, "id", where)
    where = f"source '{source_id}'"
    if not ID_PATTERN.match(source_id):
        raise ConfigError(f"{where}: id must be lowercase letters, digits and dashes")
    for key in ("feed", "site"):
        if not is_http_url(raw.get(key)):
            raise ConfigError(f"{where}: '{key}' must be an http(s) URL")
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
    return Source(
        id=source_id,
        name=_text_field(raw, "name", where),
        feed=raw["feed"].strip(),
        site=raw["site"].strip(),
        category=_text_field(raw, "category", where),
        group=_text_field(raw, "group", where),
        enabled=enabled,
        summary_from=summary_from,
        exclude_title=compiled,
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
    raw_sources = data.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise ConfigError("sources must be a non-empty list")
    sources = tuple(_parse_source(raw, i) for i, raw in enumerate(raw_sources))
    seen: set[str] = set()
    for source in sources:
        if source.id in seen:
            raise ConfigError(f"duplicate source id '{source.id}'")
        seen.add(source.id)
    return Config(settings=settings, sources=sources)


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
