import re
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from owlfeed.config import Source

ROOT = Path(__file__).resolve().parents[1]
FEEDS = Path(__file__).parent / "fixtures" / "feeds"
NOW = datetime(2026, 10, 15, 14, 0, tzinfo=timezone.utc)


def make_source(source_id="example", **overrides):
    values = dict(
        id=source_id,
        name=source_id.title(),
        feed=f"https://{source_id}.example.com/feed",
        site=f"https://{source_id}.example.com/",
        category="Cyber",
        group="Security news",
    )
    patterns = overrides.pop("exclude_title", ())
    zone = overrides.pop("timezone", None)
    if zone:
        overrides["tz"] = ZoneInfo(zone)
    values.update(overrides)
    return Source(**values, exclude_title=tuple(re.compile(p, re.I) for p in patterns))


def feed_bytes(name):
    return (FEEDS / name).read_bytes()


@pytest.fixture
def now():
    return NOW
