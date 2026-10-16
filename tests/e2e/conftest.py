"""Browser test fixtures: a static server for site/ plus a Playwright page with a fixed clock.

Set OWLFEED_CHROMIUM to a Chromium binary to use it instead of Playwright's bundled browser.
"""

import functools
import json
import os
import shutil
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

playwright_api = pytest.importorskip("playwright.sync_api")

from .sample_data import NOW, build_feed  # noqa: E402

SITE = Path(__file__).resolve().parents[2] / "site"


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


class SiteServer:
    def __init__(self, root: Path):
        self.root = root
        handler = functools.partial(QuietHandler, directory=str(root))
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def write_feed(self, feed):
        data = self.root / "data"
        data.mkdir(exist_ok=True)
        (data / "feed.json").write_text(json.dumps(feed), encoding="utf-8")

    def remove_feed(self):
        (self.root / "data" / "feed.json").unlink(missing_ok=True)

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def server(tmp_path):
    root = tmp_path / "site"
    shutil.copytree(SITE, root, ignore=shutil.ignore_patterns("data"))
    site = SiteServer(root)
    site.write_feed(build_feed())
    yield site
    site.close()


@pytest.fixture(scope="session")
def browser():
    with playwright_api.sync_playwright() as p:
        executable = os.environ.get("OWLFEED_CHROMIUM") or None
        browser = p.chromium.launch(executable_path=executable)
        yield browser
        browser.close()


def _stub_external(route):
    route.fulfill(status=200, content_type="text/html", body="<!doctype html><title>Source article</title>")


@pytest.fixture
def make_page(browser):
    contexts = []

    def make(viewport=(1280, 900), color_scheme="light"):
        context = browser.new_context(
            viewport={"width": viewport[0], "height": viewport[1]},
            color_scheme=color_scheme,
            locale="en-US",
            timezone_id="UTC",
        )
        context.route("https://**/*", _stub_external)
        contexts.append(context)
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
        page.js_errors = errors
        return page

    yield make
    for context in contexts:
        context.close()


@pytest.fixture
def page(make_page):
    page = make_page()
    page.clock.set_fixed_time(NOW)
    return page


def set_last_visit(page, iso_time):
    """Pretend the reader last left the dashboard at iso_time."""
    page.add_init_script(
        f"localStorage.setItem('owlfeed:v1:lastVisit', JSON.stringify({json.dumps(iso_time)}));"
    )
