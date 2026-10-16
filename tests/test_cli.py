import json

import pytest

from owlfeed import __main__ as cli
from owlfeed.fetch import FetchResult
from owlfeed.store import PreviousStateError

from .conftest import feed_bytes

SOURCES_YML = """
settings:
  retention_days: 7
sources:
  - id: research
    name: Example Research
    feed: https://research.example.org/feed
    site: https://research.example.org/
    category: Cyber
    group: Threat research
  - id: blog
    name: Example Blog
    feed: https://blog.example.com/feed
    site: https://blog.example.com/
    category: Cyber
    group: Security news
  - id: spare
    name: Spare
    feed: https://spare.example.com/feed
    site: https://spare.example.com/
    category: Geopolitics
    group: World news
    enabled: false
"""

FIXTURES = {
    "https://research.example.org/feed": "atom.xml",
    "https://blog.example.com/feed": "wordpress.xml",
    "https://spare.example.com/feed": "not_a_feed.html",
}


@pytest.fixture
def sources_file(tmp_path):
    path = tmp_path / "sources.yml"
    path.write_text(SOURCES_YML, encoding="utf-8")
    return path


@pytest.fixture
def fake_network(monkeypatch):
    def fake_fetch_all(sources, validators=None):
        return {s.id: FetchResult(status=200, content=feed_bytes(FIXTURES[s.feed])) for s in sources}

    monkeypatch.setattr(cli, "fetch_all", fake_fetch_all)


def run(*args):
    return cli.main([str(a) for a in args])


def test_build_writes_feed(sources_file, tmp_path, fake_network):
    out = tmp_path / "site" / "data" / "feed.json"
    assert run("--sources", sources_file, "--now", "2026-10-15T14:00:00Z", "build", "--out", out) == 0
    state = json.loads(out.read_text(encoding="utf-8"))
    assert [s["id"] for s in state["sources"]] == ["research", "blog"]  # disabled source skipped
    assert [i["title"] for i in state["items"]] == [
        "Ransomware crew targets ExampleVPN gateways",
        "Inside Operation Night Owl",
        "Hackers’ new loader abuses signed drivers",
        "Only an updated date",
    ]


def test_build_merges_previous_file(sources_file, tmp_path, fake_network):
    out = tmp_path / "feed.json"
    run("--sources", sources_file, "--now", "2026-10-15T14:00:00Z", "build", "--out", out)
    run("--sources", sources_file, "--now", "2026-10-15T14:15:00Z", "build", "--out", out, "--previous-file", out)
    state = json.loads(out.read_text(encoding="utf-8"))
    assert state["generated_at"] == "2026-10-15T14:15:00Z"
    assert {i["first_seen"] for i in state["items"]} == {"2026-10-15T14:00:00Z"}


def test_build_aborts_when_previous_feed_is_unreadable(sources_file, tmp_path, fake_network, monkeypatch):
    def broken(url):
        raise PreviousStateError("previous feed returned HTTP 503")

    monkeypatch.setattr(cli, "load_previous_url", broken)
    out = tmp_path / "feed.json"
    assert run("--sources", sources_file, "build", "--out", out, "--previous-url", "https://x.example/feed.json") == 2
    assert not out.exists()


def test_build_fails_when_every_source_fails(sources_file, tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "fetch_all", lambda sources, validators=None: {s.id: FetchResult(error="timed out") for s in sources})
    out = tmp_path / "feed.json"
    assert run("--sources", sources_file, "build", "--out", out) == 3
    assert not out.exists()


def test_check_reports_every_source(sources_file, tmp_path, fake_network, capsys):
    summary = tmp_path / "summary.md"
    code = run("--sources", sources_file, "--now", "2026-10-15T14:00:00Z", "check", "--include-disabled", "--summary-file", summary)
    assert code == 0  # a broken disabled source never fails the check
    output = capsys.readouterr().out
    assert "OK   research" in output and "FAIL spare [disabled]" in output
    assert "2/2 enabled sources healthy" in output
    markdown = summary.read_text(encoding="utf-8")
    assert "| ✅ | Example Research |" in markdown and "❌" in markdown


def test_check_strict_fails_on_broken_enabled_source(sources_file, monkeypatch, capsys):
    monkeypatch.setattr(cli, "fetch_all", lambda sources, validators=None: {s.id: FetchResult(error="HTTP 403") for s in sources})
    assert run("--sources", sources_file, "check", "--strict") == 1
    assert "0/2 enabled sources healthy" in capsys.readouterr().out


def test_invalid_config_exit_code(tmp_path):
    bad = tmp_path / "sources.yml"
    bad.write_text("sources: []", encoding="utf-8")
    assert run("--sources", bad, "build", "--out", tmp_path / "feed.json") == 4


def test_build_uses_fallback_file_when_live_feed_is_missing(sources_file, tmp_path, fake_network, monkeypatch):
    saved = tmp_path / "saved.json"
    run("--sources", sources_file, "--now", "2026-10-15T14:00:00Z", "build", "--out", saved)
    monkeypatch.setattr(cli, "load_previous_url", lambda url: None)  # Pages answered 404
    out = tmp_path / "feed.json"
    code = run("--sources", sources_file, "--now", "2026-10-15T14:15:00Z", "build", "--out", out,
               "--previous-url", "https://x.example/feed.json", "--fallback-file", saved)
    assert code == 0
    state = json.loads(out.read_text(encoding="utf-8"))
    assert {i["first_seen"] for i in state["items"]} == {"2026-10-15T14:00:00Z"}


def test_check_fences_feed_text_from_workflow_commands(sources_file, monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(
        cli, "fetch_all",
        lambda sources, validators=None: {
            s.id: FetchResult(error="HTTP 403") if s.id == "blog" else FetchResult(status=200, content=feed_bytes(FIXTURES[s.feed]))
            for s in sources
        },
    )
    run("--sources", sources_file, "check")
    lines = capsys.readouterr().out.splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith("::stop-commands::"))
    token = lines[start].split("::")[2]
    end = lines.index(f"::{token}::")
    assert start < end
    assert any(l.startswith("::warning title=Feed check::Example Blog (blog): HTTP 403") for l in lines[end:])
    assert not any(l.startswith("::warning") for l in lines[start:end])
