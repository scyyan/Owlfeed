"""End-to-end checks of the dashboard in a real browser, against a fixed clock and sample feed."""

import re
from datetime import timedelta

from playwright.sync_api import expect

from .conftest import set_last_visit
from .sample_data import ITEMS, NOW, breaking_item, build_feed, iso

TITLES = "article.item .item-title"


def open_dashboard(page, server):
    page.goto(server.url)
    expect(page.locator("article.item").first).to_be_visible()


def visible_titles(page):
    return page.locator(TITLES).all_inner_texts()


def item(page, title):
    return page.locator("article.item", has=page.locator(".item-title", has_text=title))


def wait_until(page, expression, timeout_ms=5000):
    """Poll a JS expression. (page.wait_for_function relies on eval, which the dashboard's CSP blocks.)"""
    for _ in range(timeout_ms // 50):
        if page.evaluate(expression):
            return
        page.wait_for_timeout(50)
    raise AssertionError(f"timed out waiting for: {expression}")


def test_items_are_newest_first_with_summaries_and_new_tab_links(page, server):
    open_dashboard(page, server)
    stamps = page.locator("article.item time").evaluate_all("els => els.map(e => e.dateTime)")
    assert len(stamps) == len(ITEMS)
    assert stamps == sorted(stamps, reverse=True)

    first = page.locator("article.item").first
    expect(first.locator(".item-title")).to_have_text("ExampleVPN gateways exploited to deploy ransomware")
    expect(first.locator(".item-summary")).to_contain_text("critical authentication bypass")
    expect(first.locator(".item-age")).to_have_text("12m ago")

    for link in page.locator(".item-title a").all():
        assert link.get_attribute("target") == "_blank"
        assert set(link.get_attribute("rel").split()) >= {"noopener", "noreferrer"}
        assert link.get_attribute("href").startswith("https://example.com/")
    expect(first.locator(".item-title a")).to_have_attribute("href", "https://example.com/sample-news/i01")

    with page.expect_popup() as popup:
        first.locator(".item-title a").click()
    assert popup.value.url == "https://example.com/sample-news/i01"

    expect(page.locator(".day-title")).to_have_text(["Today", "Yesterday", "Tuesday"])
    expect(item(page, "Phishing kit").locator(".item-summary")).to_have_text("No summary provided by the source.")
    expect(item(page, "Undated item").locator(".item-time")).to_have_text(re.compile(r"^~"))
    assert page.js_errors == []


def test_feed_text_is_never_treated_as_html(page, server):
    open_dashboard(page, server)
    expect(page.get_by_text("Script link that must never render")).to_have_count(0)
    markup = item(page, "Markup in a headline")
    expect(markup.locator(".item-title")).to_contain_text('<img src=x onerror="window.__xss=1">')
    expect(markup.locator("img")).to_have_count(0)
    assert page.evaluate("window.__xss") is None


def test_category_source_and_search_filters(page, server):
    open_dashboard(page, server)
    page.get_by_role("checkbox", name="Geopolitics").uncheck()
    expect(page.locator(".item-source")).not_to_contain_text(["Sample World Desk"])
    sources = set(page.locator(".item-source").all_inner_texts())
    assert sources == {"Sample CERT", "Sample Threat Research", "Sample Security News"}
    expect(page.locator("#active-filters")).to_contain_text("Cyber only")

    page.locator(".source-row", has_text="Sample CERT").hover()
    page.get_by_role("button", name="Show only Sample CERT").click()
    assert set(page.locator(".item-source").all_inner_texts()) == {"Sample CERT"}

    page.locator("#active-filters").get_by_role("button", name="Clear").click()
    expect(page.locator("article.item")).to_have_count(len(ITEMS))

    page.get_by_role("searchbox").fill("ransomware")
    expect(page.locator("article.item")).to_have_count(2)
    page.get_by_role("searchbox").fill('"supply chain" servers')
    expect(page.locator(TITLES)).to_have_text(["Supply chain intrusion targets build servers"])
    page.get_by_role("searchbox").fill("examplia ceasefire")
    expect(page.locator(TITLES)).to_have_text(["Ceasefire talks resume in the fictional Republic of Examplia"])
    page.get_by_role("searchbox").fill("no such thing anywhere")
    expect(page.get_by_text("Nothing matches these filters")).to_be_visible()


def test_watchlist_highlights_items(page, server):
    open_dashboard(page, server)
    page.get_by_role("textbox", name="Add a watchlist term").fill("ExampleVPN")
    page.get_by_role("button", name="Add", exact=True).click()
    expect(page.locator("article.is-watch")).to_have_count(2)
    expect(page.locator("article.item mark").first).to_have_text("ExampleVPN")
    expect(page.locator('[data-view="watchlist"] .count')).to_have_text("2")

    page.locator('[data-view="watchlist"]').click()
    expect(page.locator("article.item")).to_have_count(2)

    page.reload()
    expect(page.locator(".chip-label")).to_have_text(["ExampleVPN"])
    expect(page.locator("article.item")).to_have_count(2)  # the view is remembered too

    page.get_by_role("button", name="Remove ExampleVPN from watchlist").click()
    expect(page.get_by_text("Your watchlist is empty")).to_be_visible()


def test_read_and_saved_items_persist(page, server):
    open_dashboard(page, server)
    target = item(page, "Supply chain intrusion")
    target.get_by_role("button", name="Save for later").click()
    expect(target.get_by_role("button", name="Remove from saved")).to_have_attribute("aria-pressed", "true")
    expect(page.locator('[data-view="saved"] .count')).to_have_text("1")

    with page.expect_popup():
        item(page, "ExampleVPN gateways").locator(".item-title a").click()
    expect(item(page, "ExampleVPN gateways")).to_have_class(re.compile(r"\bis-read\b"))
    expect(page.locator('[data-view="unread"] .count')).to_have_text(str(len(ITEMS) - 1))

    page.reload()
    expect(item(page, "ExampleVPN gateways")).to_have_class(re.compile(r"\bis-read\b"))
    page.locator('[data-view="saved"]').click()
    expect(page.locator(TITLES)).to_have_text(["Supply chain intrusion targets build servers"])

    page.locator('[data-view="unread"]').click()
    page.get_by_role("button", name="Mark all read").click()
    expect(page.get_by_text("You're all caught up")).to_be_visible()
    expect(page.locator('[data-view="unread"] .count')).to_have_text("0")


def test_saved_items_outlive_the_feed(page, server):
    open_dashboard(page, server)
    item(page, "Weekly vulnerability summary").get_by_role("button", name="Save for later").click()
    feed = build_feed()
    feed["items"] = [i for i in feed["items"] if i["id"] != "i09"]  # aged out of the 7-day window
    server.write_feed(feed)
    page.reload()
    expect(page.get_by_text("Weekly vulnerability summary")).to_have_count(0)
    page.locator('[data-view="saved"]').click()
    expect(page.locator(TITLES)).to_have_text(["Weekly vulnerability summary"])


def test_new_since_last_visit(page, server):
    set_last_visit(page, iso(NOW - timedelta(minutes=100)))
    open_dashboard(page, server)
    # i01, i02 and i03 were first seen less than 100 minutes ago.
    expect(page.locator(".badge-new")).to_have_count(3)
    expect(page.locator("#new-chip")).to_have_text("3 new")
    page.locator("#new-chip").click()
    expect(page.locator("article.item")).to_have_count(3)
    page.reload()  # reloading keeps the same baseline within the tab session
    expect(page.locator(".badge-new")).to_have_count(3)


def test_auto_refresh_adds_new_items(make_page, server):
    page = make_page()
    page.clock.install(time=NOW)
    open_dashboard(page, server)
    expect(page.locator("#new-chip")).to_be_hidden()  # first visit: nothing is "new" yet

    server.write_feed(build_feed(extra_items=[breaking_item()], generated_at=NOW + timedelta(minutes=5)))
    # Just past the 5-minute poll, so the 4-second "added" toast is still showing.
    page.clock.run_for(5 * 60_000 + 1_000)
    breaking = item(page, "Breaking: sample item")
    expect(breaking).to_be_visible()
    expect(breaking.locator(".badge-new")).to_be_visible()
    expect(page.locator("#status")).to_contain_text("1 new item added")
    expect(page.locator("#updated")).to_have_text("Updated just now")


def test_new_items_wait_behind_a_pill_when_scrolled_down(make_page, server):
    page = make_page(viewport=(1280, 600))
    page.clock.install(time=NOW)
    open_dashboard(page, server)
    page.evaluate("window.scrollTo(0, 1500)")  # instant; smooth wheel scrolling waits on the fake clock
    wait_until(page, "window.scrollY > 400")

    server.write_feed(build_feed(extra_items=[breaking_item()], generated_at=NOW + timedelta(minutes=5)))
    page.clock.run_for(5 * 60_000 + 31_000)
    pill = page.locator("#new-pill")
    expect(pill).to_have_text("↑ 1 new item")
    expect(page.get_by_text("Breaking: sample item")).to_have_count(0)
    pill.click()
    expect(item(page, "Breaking: sample item")).to_be_visible()
    expect(pill).to_be_hidden()


def test_stale_feed_and_source_health_are_flagged(page, server):
    server.write_feed(build_feed(generated_at=NOW - timedelta(hours=3)))
    open_dashboard(page, server)
    expect(page.locator("#updated")).to_have_text("Updated 3 hours ago")
    expect(page.locator("#updated")).to_have_class(re.compile(r"\bis-stale\b"))
    expect(page.locator(".health-summary")).to_have_text("4 of 5 sources OK")
    error_dot = page.locator(".source-row", has_text="Sample Security News").locator(".health-dot")
    expect(error_dot).to_have_class(re.compile(r"\bis-error\b"))
    expect(error_dot).to_have_attribute("title", re.compile(r"HTTP 403"))


def test_waiting_for_first_refresh(page, server):
    server.remove_feed()
    page.goto(server.url)
    expect(page.get_by_text("No feed data published yet")).to_be_visible()


def test_mobile_drawer(make_page, server):
    page = make_page(viewport=(390, 844))
    page.clock.set_fixed_time(NOW)
    open_dashboard(page, server)
    sidebar = page.locator("#sidebar")
    assert sidebar.bounding_box()["x"] < 0  # off screen
    page.get_by_role("button", name="Open views and filters").click()
    expect(page.get_by_role("button", name="Open views and filters")).to_have_attribute("aria-expanded", "true")
    wait_until(page, "document.getElementById('sidebar').getBoundingClientRect().x >= 0")
    page.keyboard.press("Escape")
    wait_until(page, "document.getElementById('sidebar').getBoundingClientRect().x < 0")
    no_horizontal_scroll = page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert no_horizontal_scroll


def test_theme_toggle_persists(page, server):
    open_dashboard(page, server)
    page.get_by_role("button", name="Switch to dark mode").click()
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    page.reload()
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    expect(page.get_by_role("button", name="Switch to light mode")).to_be_visible()


def test_backup_and_restore(page, server, tmp_path):
    open_dashboard(page, server)
    page.get_by_role("textbox", name="Add a watchlist term").fill("Examplia")
    page.get_by_role("button", name="Add", exact=True).click()
    with page.expect_download() as download:
        page.get_by_role("button", name="Back up settings").click()
    backup = tmp_path / "backup.json"
    download.value.save_as(backup)

    page.evaluate("localStorage.clear()")
    page.reload()
    expect(page.locator(".chip-label")).to_have_count(0)
    page.locator("#import-input").set_input_files(str(backup))
    expect(page.locator(".chip-label")).to_have_text(["Examplia"])
    expect(page.locator("#status")).to_contain_text("1 watchlist terms added")


def hide_and_show(page, away_ms):
    """Simulate switching away from the tab for away_ms (needs page.clock.install)."""
    page.evaluate(
        "Object.defineProperty(document, 'visibilityState', {configurable: true, get: () => 'hidden'});"
        "document.dispatchEvent(new Event('visibilitychange'))"
    )
    page.clock.run_for(away_ms)
    page.evaluate(
        "Object.defineProperty(document, 'visibilityState', {configurable: true, get: () => 'visible'});"
        "document.dispatchEvent(new Event('visibilitychange'))"
    )


def test_two_tabs_merge_and_sync(make_page, server):
    tab_a = make_page()
    tab_a.clock.set_fixed_time(NOW)
    open_dashboard(tab_a, server)
    tab_b = tab_a.context.new_page()
    tab_b.clock.set_fixed_time(NOW)
    open_dashboard(tab_b, server)

    item(tab_a, "Supply chain intrusion").get_by_role("button", name="Save for later").click()
    item(tab_b, "Regional summit").get_by_role("button", name="Save for later").click()
    # Tab A hears about tab B's change without reloading.
    expect(item(tab_a, "Regional summit").locator(".btn-save")).to_have_attribute("aria-pressed", "true")
    expect(tab_a.locator('[data-view="saved"] .count')).to_have_text("2")
    tab_a.reload()
    expect(tab_a.locator('[data-view="saved"] .count')).to_have_text("2")


def test_last_visit_is_the_feed_build_that_was_seen(make_page, server):
    built = NOW - timedelta(minutes=10)
    server.write_feed(build_feed(generated_at=built))
    page = make_page()
    page.clock.set_fixed_time(NOW)
    open_dashboard(page, server)
    page.goto("about:blank")  # leaving the page records the visit
    check = page.context.new_page()
    check.goto(server.url)
    assert check.evaluate("JSON.parse(localStorage.getItem('owlfeed:v1:lastVisit'))") == iso(built)


def test_new_badges_reset_after_a_long_absence(make_page, server):
    page = make_page()
    set_last_visit(page, iso(NOW - timedelta(minutes=100)))
    page.clock.install(time=NOW)
    open_dashboard(page, server)
    expect(page.locator(".badge-new")).to_have_count(3)
    hide_and_show(page, 5 * 60_000)  # a short break keeps the same visit
    expect(page.locator(".badge-new")).to_have_count(3)
    hide_and_show(page, 31 * 60_000)  # a long one starts a new visit: everything was seen
    expect(page.locator(".badge-new")).to_have_count(0)
    expect(page.locator("#new-chip")).to_be_hidden()


def test_drawer_is_modal_on_phones(make_page, server):
    page = make_page(viewport=(390, 844))
    page.clock.set_fixed_time(NOW)
    open_dashboard(page, server)
    assert page.evaluate("document.getElementById('sidebar').inert") is True
    page.get_by_role("button", name="Open views and filters").click()
    assert page.evaluate("document.activeElement.id") == "sidebar-close"
    assert page.evaluate("document.getElementById('main').inert") is True
    assert page.evaluate("document.getElementById('sidebar').inert") is False
    page.keyboard.press("Escape")
    assert page.evaluate("document.activeElement.id") == "menu-btn"
    assert page.evaluate("document.getElementById('sidebar').inert") is True

    page.get_by_role("button", name="Open views and filters").click()
    page.set_viewport_size({"width": 1280, "height": 900})  # rotating to a wide screen closes it
    wait_until(page, "!document.body.classList.contains('drawer-open')")
    assert page.evaluate("document.getElementById('main').inert || document.getElementById('sidebar').inert") is False


def test_restore_is_keyboard_operable(page, server):
    open_dashboard(page, server)
    page.locator("#import-btn").focus()
    with page.expect_file_chooser() as chooser:
        page.keyboard.press("Enter")
    assert chooser.value is not None


def test_restarring_an_aged_out_saved_item(page, server):
    open_dashboard(page, server)
    item(page, "Weekly vulnerability summary").get_by_role("button", name="Save for later").click()
    feed = build_feed()
    feed["items"] = [i for i in feed["items"] if i["id"] != "i09"]
    server.write_feed(feed)
    page.reload()
    page.locator('[data-view="saved"]').click()
    saved = item(page, "Weekly vulnerability summary")
    saved.get_by_role("button", name="Remove from saved").click()
    saved.get_by_role("button", name="Save for later").click()
    expect(saved.locator(".btn-save")).to_have_attribute("aria-pressed", "true")
    page.reload()
    expect(page.locator(TITLES)).to_have_text(["Weekly vulnerability summary"])


def test_arrivals_hidden_by_filters_are_not_announced(make_page, server):
    page = make_page()
    page.clock.install(time=NOW)
    open_dashboard(page, server)
    page.get_by_role("checkbox", name="Geopolitics").uncheck()
    server.write_feed(build_feed(extra_items=[breaking_item()], generated_at=NOW + timedelta(minutes=5)))
    page.clock.run_for(5 * 60_000 + 1_000)
    expect(page.locator("#updated")).to_have_text("Updated just now")  # the refresh was applied
    expect(page.locator("#status")).to_be_hidden()
    expect(page.get_by_text("Breaking: sample item")).to_have_count(0)


def test_auto_refresh_keeps_keyboard_focus(make_page, server):
    page = make_page()
    page.clock.install(time=NOW)
    open_dashboard(page, server)
    item(page, "Advisory: Critical flaw").get_by_role("button", name="Save for later").focus()
    server.write_feed(build_feed(extra_items=[breaking_item()], generated_at=NOW + timedelta(minutes=5)))
    page.clock.run_for(5 * 60_000 + 1_000)
    expect(item(page, "Breaking: sample item")).to_be_visible()
    focused = page.evaluate("[document.activeElement.dataset.action, document.activeElement.closest('article')?.dataset.id]")
    assert focused == ["save", "i03"]


def test_empty_state_explains_filters(page, server):
    open_dashboard(page, server)
    item(page, "Supply chain intrusion").get_by_role("button", name="Save for later").click()
    page.locator('[data-view="saved"]').click()
    page.get_by_role("searchbox").fill("no such thing")
    expect(page.get_by_text("Nothing matches these filters")).to_be_visible()
    expect(page.get_by_text("Nothing saved yet")).to_have_count(0)


def test_stale_banner_shows_on_phones(make_page, server):
    server.write_feed(build_feed(generated_at=NOW - timedelta(hours=3)))
    page = make_page(viewport=(390, 844))
    page.clock.set_fixed_time(NOW)
    open_dashboard(page, server)
    expect(page.locator("#stale-banner")).to_be_visible()
    expect(page.locator("#stale-banner")).to_contain_text("last updated 3 hours ago")
