"""Command line: `python -m owlfeed build`, `check` and `stamp`."""

from __future__ import annotations

import argparse
import io
import logging
import os
import re
import secrets
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import feedparser

from .config import Config, ConfigError, Source, load_config
from .fetch import fetch_all
from .parse import Entry, FeedParseError, parse_feed
from .stamp import stamp_site
from .store import (
    AllSourcesFailed,
    PreviousStateError,
    SourceOutcome,
    iso,
    load_previous_file,
    load_previous_url,
    merge,
    parse_iso,
    previous_validators,
    write_state,
)

log = logging.getLogger("owlfeed")


def _now(value: str | None) -> datetime:
    if value:
        moment = parse_iso(value)
        if moment is None:
            raise SystemExit(f"--now must be an ISO 8601 timestamp, got {value!r}")
        return moment
    return datetime.now(timezone.utc).replace(microsecond=0)


def collect(config: Config, sources: tuple[Source, ...], validators: dict, now: datetime) -> dict[str, SourceOutcome]:
    results = fetch_all(sources, validators)
    outcomes: dict[str, SourceOutcome] = {}
    for source in sources:
        result = results[source.id]
        if result.error:
            outcomes[source.id] = SourceOutcome(result, None, result.error)
        elif result.not_modified:
            outcomes[source.id] = SourceOutcome(result, None, None)
        else:
            try:
                entries = parse_feed(result.content or b"", source, config.settings, now, result.content_type)
            except FeedParseError as exc:
                outcomes[source.id] = SourceOutcome(result, None, str(exc))
            except Exception as exc:  # noqa: BLE001 - a parser bug on one feed must not sink the build
                log.exception("Unexpected error parsing %s", source.id)
                outcomes[source.id] = SourceOutcome(result, None, f"could not parse feed ({type(exc).__name__})")
            else:
                outcomes[source.id] = SourceOutcome(result, entries, None)
    return outcomes


def cmd_build(args: argparse.Namespace) -> int:
    config = load_config(args.sources)
    now = _now(args.now)
    try:
        if args.previous_url:
            previous = load_previous_url(args.previous_url)
            if previous is None and args.fallback_file:
                # The live feed is missing (first run, or Pages answering 404 for a moment). A saved
                # copy from an earlier run keeps the 7-day history instead of starting from scratch.
                previous = load_previous_file(args.fallback_file)
                if previous is not None:
                    log.info("Using the saved copy %s instead", args.fallback_file)
        elif args.previous_file:
            previous = load_previous_file(args.previous_file)
        else:
            previous = None
    except PreviousStateError as exc:
        log.error("%s. Aborting so the live dashboard keeps its current data.", exc)
        return 2

    outcomes = collect(config, config.enabled_sources, previous_validators(previous), now)
    for source in config.enabled_sources:
        outcome = outcomes[source.id]
        if outcome.error:
            log.warning("%-28s FAILED: %s", source.id, outcome.error)
        elif outcome.entries is None:
            log.info("%-28s not modified", source.id)
        else:
            log.info("%-28s %d entries", source.id, len(outcome.entries))

    try:
        state = merge(previous, config, outcomes, now)
    except AllSourcesFailed as exc:
        log.error("%s. Not writing a feed.", exc)
        return 3
    write_state(state, args.out)
    healthy = sum(1 for row in state["sources"] if row["status"] == "ok")
    log.info(
        "Wrote %d items from %d/%d healthy sources to %s",
        len(state["items"]),
        healthy,
        len(state["sources"]),
        args.out,
    )
    return 0


@dataclass
class CheckRow:
    source: Source
    status: int | None
    entries: list[Entry] | None
    error: str | None


def _age(moment: datetime | None, now: datetime) -> str:
    if moment is None:
        return "no date"
    hours = (now - moment).total_seconds() / 3600
    if hours < 1:
        return f"{max(0, round(hours * 60))}m ago"
    if hours < 48:
        return f"{round(hours)}h ago"
    return f"{round(hours / 24)}d ago"


def _inspect(source_id: str, outcome: SourceOutcome) -> None:
    """Print raw feed details, for working out why a feed parses oddly."""
    result = outcome.result
    print(f"\n=== inspect {source_id}: HTTP {result.status}, content-type {result.content_type!r}")
    content = result.content or b""
    print(content[:1500].decode("utf-8", errors="replace"))
    parsed = feedparser.parse(io.BytesIO(content), response_headers={"content-type": result.content_type or ""})
    print(f"--- feedparser version={parsed.get('version')!r} bozo={parsed.get('bozo')} entries={len(parsed.entries)}")
    for entry in parsed.entries[:2]:
        for key in sorted(entry):
            print(f"    {key}: {str(entry[key])[:200]!s}")
        print("    ---")


_MARKDOWN_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+!|~])")


def _cell(text: str, limit: int = 90) -> str:
    """Feed text made inert for a Markdown table cell: no links, images, HTML or column breaks."""
    text = " ".join(text.split())
    text = text if len(text) <= limit else text[: limit - 1] + "…"
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return _MARKDOWN_SPECIAL.sub(r"\\\1", text)


def _newest(entries: list[Entry]) -> datetime | None:
    return max((e.published for e in entries if e.published), default=None)


def cmd_check(args: argparse.Namespace) -> int:
    config = load_config(args.sources)
    now = _now(args.now)
    sources = config.sources if args.include_disabled else config.enabled_sources
    outcomes = collect(config, sources, {}, now)
    rows = []
    for source in sources:
        outcome = outcomes[source.id]
        rows.append(CheckRow(source, outcome.result.status, outcome.entries, outcome.error))

    in_actions = os.environ.get("GITHUB_ACTIONS") == "true"
    # Feed text is printed below; stop the Actions runner from treating any of it as a
    # workflow command ("::error::", "::add-mask::" ...). Our own warnings go out afterwards.
    resume = secrets.token_hex(16)
    if in_actions:
        print(f"::stop-commands::{resume}")
    failures = 0
    warnings: list[str] = []
    print(f"Owlfeed feed check at {iso(now)}: {len(rows)} sources\n")
    for row in rows:
        entries = row.entries or []
        label = "OK  " if not row.error and entries else ("FAIL" if row.error else "EMPTY")
        if label != "OK  " and row.source.enabled:
            failures += 1
            warnings.append(f"{row.source.name} ({row.source.id}): {row.error or 'feed has no items'}")
        flag = "" if row.source.enabled else " [disabled]"
        newest = _newest(entries)
        dated = sum(1 for e in entries if e.published)
        print(
            f"{label} {row.source.id}{flag} | {row.source.category} / {row.source.group} | "
            f"HTTP {row.status} | {len(entries)} items ({dated} dated) | newest {_age(newest, now)}"
            + (f" | ERROR: {row.error}" if row.error else "")
        )
        for entry in entries[: args.samples]:
            stamp = iso(entry.published) if entry.published else "no date"
            print(f"     - [{stamp}] {entry.title}")
            print(f"       {entry.url}")
            print(f"       {entry.summary or '(no summary)'}")
        print()

    enabled = [r for r in rows if r.source.enabled]
    healthy = len(enabled) - failures
    print(f"{healthy}/{len(enabled)} enabled sources healthy")

    for source_id in args.inspect or []:
        outcome = outcomes.get(source_id)
        if outcome is None:
            print(f"\n--inspect {source_id}: no such source")
            continue
        _inspect(source_id, outcome)

    if in_actions:
        print(f"::{resume}::")
        for warning in warnings:
            # Error text comes from our own code, but strip anything that could end the command early.
            print(f"::warning title=Feed check::{warning.replace('::', ': :').replace(chr(10), ' ')}")

    if args.summary_file:
        lines = [
            "## Owlfeed feed check",
            "",
            f"{healthy}/{len(enabled)} enabled sources healthy at {iso(now)}.",
            "",
            "| | Source | Group | HTTP | Items | Newest | Latest headline |",
            "|---|---|---|---|---|---|---|",
        ]
        for row in rows:
            entries = row.entries or []
            mark = "✅" if not row.error and entries else ("❌" if row.error else "⚠️")
            name = _cell(row.source.name, 40) + ("" if row.source.enabled else " *(disabled)*")
            latest = entries[0].title if entries else (row.error or "no items")
            newest = _age(_newest(entries), now) if entries else ""
            lines.append(
                f"| {mark} | {name} | {_cell(row.source.group, 30)} | {row.status or ''} | "
                f"{len(entries)} | {newest} | {_cell(latest)} |"
            )
        with open(args.summary_file, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    return 1 if args.strict and failures else 0


def cmd_stamp(args: argparse.Namespace) -> int:
    try:
        version = stamp_site(Path(args.site))
    except FileNotFoundError as exc:
        log.error("%s", exc)
        return 2
    log.info("Stamped %s with version %s", args.site, version)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="owlfeed", description="Build the Owlfeed dashboard data.")
    parser.add_argument("--sources", default="sources.yml", help="path to sources.yml")
    parser.add_argument("--now", help=argparse.SUPPRESS)  # fixed clock for tests
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser("build", help="fetch feeds and write feed.json")
    build.add_argument("--out", default="site/data/feed.json", help="where to write feed.json")
    previous = build.add_mutually_exclusive_group()
    previous.add_argument("--previous-url", help="URL of the currently deployed feed.json")
    previous.add_argument("--previous-file", help="path to a previous feed.json")
    build.add_argument("--fallback-file", help="saved feed.json to use if --previous-url answers 404")
    build.set_defaults(func=cmd_build)

    check = commands.add_parser("check", help="report the health of every feed")
    check.add_argument("--include-disabled", action="store_true", help="also check disabled sources")
    check.add_argument("--samples", type=int, default=2, help="sample entries to print per source")
    check.add_argument("--summary-file", help="append a Markdown report (e.g. $GITHUB_STEP_SUMMARY)")
    check.add_argument("--strict", action="store_true", help="exit 1 if any enabled source fails")
    check.add_argument("--inspect", action="append", metavar="ID", help="dump raw details for a source (repeatable)")
    check.set_defaults(func=cmd_check)

    stamp = commands.add_parser("stamp", help="version CSS/JS URLs in a site directory before publishing")
    stamp.add_argument("site", nargs="?", default="site", help="the site directory to rewrite in place")
    stamp.set_defaults(func=cmd_stamp)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stderr)
    try:
        return args.func(args)
    except ConfigError as exc:
        log.error("Invalid %s: %s", Path(args.sources).name, exc)
        return 4


if __name__ == "__main__":
    sys.exit(main())
