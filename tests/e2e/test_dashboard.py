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

    page.locator(".source-group", has=page.locator(".source-row", has_text="Sample CERT")).locator("summary").click()
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
    expect(page.get_by_text("Nothing matches “no such thing anywhere”")).to_be_visible()


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
    expect(target.get_by_role("button", name="Save for later", pressed=True)).to_have_attribute("aria-pressed", "true")
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
    page.locator("#mark-all-read").click()
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
    expect(page.locator('[data-view="new"] .count')).to_have_text("3")
    page.locator('[data-view="new"]').click()
    expect(page.locator("article.item")).to_have_count(3)
    page.reload()  # reloading keeps the same baseline within the tab session
    expect(page.locator(".badge-new")).to_have_count(3)


def test_auto_refresh_adds_new_items(make_page, server):
    page = make_page()
    page.clock.install(time=NOW)
    open_dashboard(page, server)
    # First visit: the last 24 hours count as new, so the New view starts useful.
    expect(page.locator('[data-view="new"] .count')).not_to_have_text("0")

    server.write_feed(build_feed(extra_items=[breaking_item()], generated_at=NOW + timedelta(minutes=5)))
    # Just past the 5-minute poll, so the 4-second "added" toast is still showing.
    page.clock.run_for(5 * 60_000 + 1_000)
    breaking = item(page, "Breaking: sample item")
    expect(breaking).to_be_visible()
    expect(breaking.locator(".badge-arrived")).to_have_text("Just in")
    expect(page.locator("#status")).to_contain_text("1 just arrived")
    expect(page.locator("#updated")).to_have_text("Updated just now")
    expect(page).to_have_title("(1) Owlfeed")  # a glance at the tab says what changed
    breaking.get_by_role("button", name="Mark as read").click()
    expect(page).to_have_title("Owlfeed")


def test_new_items_wait_behind_a_pill_when_scrolled_down(make_page, server):
    page = make_page(viewport=(1280, 600))
    page.clock.install(time=NOW)
    open_dashboard(page, server)
    page.evaluate("window.scrollTo(0, 1500)")  # instant; smooth wheel scrolling waits on the fake clock
    wait_until(page, "window.scrollY > 400")

    server.write_feed(build_feed(extra_items=[breaking_item()], generated_at=NOW + timedelta(minutes=5)))
    page.clock.run_for(5 * 60_000 + 31_000)
    pill = page.locator("#new-pill")
    expect(pill).to_have_text("↑ 1 just arrived")
    expect(page.get_by_text("Breaking: sample item")).to_have_count(0)
    pill.click()
    expect(item(page, "Breaking: sample item")).to_be_visible()
    expect(pill).to_be_hidden()


def test_stale_feed_and_source_health_are_flagged(page, server):
    server.write_feed(build_feed(generated_at=NOW - timedelta(hours=3)))
    open_dashboard(page, server)
    expect(page.locator("#updated")).to_have_text("Updated 3 hours ago")
    expect(page.locator("#updated")).to_have_class(re.compile(r"\bis-stale\b"))
    expect(page.locator("#watch-sources")).to_have_text("4/5")
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
    expect(page.locator("#status")).to_contain_text("1 watchlist term added")


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
    expect(page.locator('[data-view="new"] .count')).to_have_text("0")


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
    assert page.evaluate("document.activeElement.id") == "tab-filters"
    assert page.evaluate("document.getElementById('sidebar').inert") is True

    page.get_by_role("button", name="Open views and filters").click()
    page.set_viewport_size({"width": 1280, "height": 900})  # rotating to a wide screen closes it
    wait_until(page, "!document.body.classList.contains('drawer-open')")
    assert page.evaluate("document.getElementById('main').inert || document.getElementById('sidebar').inert") is False


def test_restore_is_keyboard_operable(page, server):
    open_dashboard(page, server)
    # Count requests to open the file picker. (Whether a headless browser then reports a native
    # chooser for keyboard activation differs between builds; a click opening it is covered by
    # test_restore_from_the_phone_drawer_is_announced.)
    page.evaluate(
        "window.__pickerRequests = 0;"
        "document.getElementById('import-input').addEventListener('click', (event) => {"
        "  window.__pickerRequests++; event.preventDefault(); })"
    )
    page.locator("#import-btn").focus()
    page.keyboard.press("Enter")
    page.keyboard.press("Space")
    wait_until(page, "window.__pickerRequests === 2")
    assert page.evaluate("document.activeElement.id") == "import-btn"


def test_restarring_an_aged_out_saved_item(page, server):
    open_dashboard(page, server)
    item(page, "Weekly vulnerability summary").get_by_role("button", name="Save for later").click()
    feed = build_feed()
    feed["items"] = [i for i in feed["items"] if i["id"] != "i09"]
    server.write_feed(feed)
    page.reload()
    page.locator('[data-view="saved"]').click()
    saved = item(page, "Weekly vulnerability summary")
    saved.get_by_role("button", name="Save for later", pressed=True).click()
    expect(page.locator(TITLES)).to_have_count(0)  # Saved lists what is starred: no ghost row
    page.locator("#status").get_by_role("button", name="Undo").click()
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
    expect(page.get_by_text("Nothing matches “no such thing”")).to_be_visible()
    expect(page.get_by_text("Nothing saved yet")).to_have_count(0)


def test_stale_banner_shows_on_phones(make_page, server):
    server.write_feed(build_feed(generated_at=NOW - timedelta(hours=3)))
    page = make_page(viewport=(390, 844))
    page.clock.set_fixed_time(NOW)
    open_dashboard(page, server)
    expect(page.locator("#stale-banner")).to_be_visible()
    expect(page.locator("#stale-banner")).to_contain_text("last updated 3 hours ago")


def test_restore_from_the_phone_drawer_is_announced(make_page, server, tmp_path):
    backup = tmp_path / "backup.json"
    backup.write_text('{"app": "owlfeed", "version": 1, "watchlist": ["Examplia"]}', encoding="utf-8")
    page = make_page(viewport=(390, 844))
    page.clock.set_fixed_time(NOW)
    open_dashboard(page, server)
    page.get_by_role("button", name="Open views and filters").click()
    with page.expect_file_chooser() as chooser:
        page.get_by_role("button", name="Restore").click()
    chooser.value.set_files(str(backup))
    expect(page.locator("#announcer")).to_contain_text("1 watchlist term added")
    assert page.evaluate("document.getElementById('announcer').closest('[inert]')") is None
    expect(page.locator("#status")).to_be_visible()


def test_stale_banner_text_is_stable_between_ticks(make_page, server):
    server.write_feed(build_feed(generated_at=NOW - timedelta(hours=3)))
    page = make_page()
    page.clock.install(time=NOW)
    open_dashboard(page, server)
    page.evaluate(
        "window.__bannerChanges = 0;"
        "new MutationObserver(() => window.__bannerChanges++)"
        ".observe(document.getElementById('stale-text'), {childList: true, characterData: true, subtree: true})"
    )
    page.clock.run_for(5 * 30_000)  # five ticks within the same hour
    assert page.evaluate("window.__bannerChanges") == 0


def test_clearing_search_with_escape_returns_to_the_newest_items(make_page, server):
    page = make_page(viewport=(1280, 500))
    page.clock.set_fixed_time(NOW)
    open_dashboard(page, server)
    page.get_by_role("searchbox").fill("sample")
    expect(page.locator("#active-filters")).to_contain_text("Search: sample")
    page.evaluate("window.scrollTo(0, 900)")
    page.get_by_role("searchbox").press("Escape")
    wait_until(page, "window.scrollY === 0")
    expect(page.locator("article.item")).to_have_count(len(ITEMS))


def test_focus_stays_in_the_feed_when_its_last_item_goes(make_page, server):
    page = make_page()
    page.clock.install(time=NOW)
    open_dashboard(page, server)
    page.get_by_role("searchbox").fill('"Advisory: Critical flaw"')
    expect(page.locator("article.item")).to_have_count(1)
    item(page, "Advisory: Critical flaw").get_by_role("button", name="Save for later").focus()
    feed = build_feed(generated_at=NOW + timedelta(minutes=5))
    feed["items"] = [i for i in feed["items"] if i["id"] != "i03"]
    server.write_feed(feed)
    page.clock.run_for(5 * 60_000 + 1_000)
    expect(page.get_by_text('Nothing matches "Advisory: Critical flaw"')).to_be_visible()
    # Only the search narrows the view, so the empty state offers to clear just that.
    assert page.evaluate("document.activeElement.dataset.emptyAction") == "clear-search"


def test_clear_filters_focus_depends_on_how_it_was_pressed(page, server):
    open_dashboard(page, server)
    search = page.get_by_role("searchbox")
    search.fill("no such thing")
    page.get_by_role("button", name="Clear search").click()
    expect(page.locator("article.item")).to_have_count(len(ITEMS))
    # A tap or click goes to the newest item, so no on-screen keyboard opens over the feed...
    assert page.evaluate("document.activeElement.closest('.item-title') !== null")
    assert page.evaluate("document.activeElement.closest('article').dataset.id") == "i01"
    # ...while the keyboard continues in the search box.
    search.fill("no such thing")
    page.get_by_role("button", name="Clear search").press("Enter")
    expect(page.locator("article.item")).to_have_count(len(ITEMS))
    assert page.evaluate("document.activeElement.id") == "search"


def test_toast_never_blocks_taps(page, server):
    open_dashboard(page, server)
    page.evaluate("document.getElementById('status').hidden = false")
    assert page.evaluate("getComputedStyle(document.getElementById('status')).pointerEvents") == "none"


def test_focus_stays_on_an_empty_state_without_a_button_across_refreshes(make_page, server):
    page = make_page()
    page.clock.install(time=NOW)
    open_dashboard(page, server)
    item(page, "ExampleVPN").get_by_role("button", name="Save for later").click()
    page.locator('[data-view="saved"]').click()
    expect(page.locator("article.item")).to_have_count(1)
    unsave = item(page, "ExampleVPN").get_by_role("button", name="Save for later", pressed=True)
    unsave.focus()
    page.keyboard.press("Enter")
    for minutes in (5, 10):  # the first refresh empties the view, the second re-renders it
        server.write_feed(build_feed(generated_at=NOW + timedelta(minutes=minutes)))
        page.clock.run_for(5 * 60_000 + 1_000)
        expect(page.get_by_text("Nothing saved yet")).to_be_visible()
        assert page.evaluate("document.activeElement.classList.contains('empty')")
        assert page.evaluate("document.activeElement.closest('#feed') !== null")


def test_bar_clear_focus_depends_on_how_it_was_pressed(page, server):
    open_dashboard(page, server)
    search = page.get_by_role("searchbox")
    # The search's own token: removing the last filter goes where Clear used to.
    clear = page.locator("#active-filters").get_by_role("button", name="Remove filter: Search: Example*")
    search.fill("Example*")
    expect(page.locator("article.item").first).to_be_visible()
    clear.click()
    expect(page.locator("article.item")).to_have_count(len(ITEMS))
    assert page.evaluate("document.activeElement.closest('article')?.dataset.id") == "i01"
    search.fill("Example*")
    clear.press("Enter")
    expect(page.locator("article.item")).to_have_count(len(ITEMS))
    assert page.evaluate("document.activeElement.id") == "search"


def test_mark_all_read_names_its_scope_and_can_be_undone(page, server):
    open_dashboard(page, server)
    button = page.locator("#mark-all-read")
    expect(button).to_have_text(f"Mark {len(ITEMS)} read")
    item(page, "ExampleVPN gateways").get_by_role("button", name="Mark as read").click()
    expect(button).to_have_text(f"Mark {len(ITEMS) - 1} read")

    button.click()
    expect(page.locator('[data-view="unread"] .count')).to_have_text("0")
    expect(button).to_be_disabled()
    expect(page.locator("#status-text")).to_have_text(f"Marked {len(ITEMS) - 1} items as read")
    undo = page.locator("#status").get_by_role("button", name="Undo")
    undo.click()
    # Only what the button marked comes back; the item read beforehand stays read.
    expect(page.locator('[data-view="unread"] .count')).to_have_text(str(len(ITEMS) - 1))
    expect(item(page, "ExampleVPN gateways")).to_have_class(re.compile(r"\bis-read\b"))
    expect(page.locator("#status-text")).to_have_text(f"Restored {len(ITEMS) - 1} items to unread")
    expect(undo).to_be_hidden()


def test_undo_mark_all_from_the_keyboard(page, server):
    open_dashboard(page, server)
    page.locator("#mark-all-read").click()
    expect(page.locator('[data-view="unread"] .count')).to_have_text("0")
    page.keyboard.press("Control+z")
    expect(page.locator('[data-view="unread"] .count')).to_have_text(str(len(ITEMS)))


def test_phones_mark_all_read_from_the_drawer(make_page, server):
    page = make_page(viewport=(390, 800))
    open_dashboard(page, server)
    expect(page.locator("#mark-all-read")).to_be_hidden()
    page.get_by_role("button", name="Open views and filters").click()
    page.locator("#mark-all-read-drawer").click()
    expect(page.locator("#sidebar")).not_to_be_in_viewport()
    expect(page.locator("#status").get_by_role("button", name="Undo")).to_be_visible()


def test_watch_status_shows_freshness_and_health_at_every_width(make_page, server):
    for viewport, expected in (((1280, 900), "Updated just now"), ((390, 800), "now")):
        page = make_page(viewport=viewport)
        page.clock.set_fixed_time(NOW)
        open_dashboard(page, server)
        watch = page.locator("#watch-btn")
        expect(watch).to_be_visible()
        expect(watch).to_have_attribute("data-state", "fresh")
        expect(page.locator("#watch-flag")).to_be_hidden()
        expect(watch).to_contain_text(expected)
        expect(page.locator("#watch-sources")).to_have_text("4/5")
        expect(watch).to_have_class(re.compile(r"\bhas-failing\b"))
        expect(watch).to_have_attribute("aria-label", "Feed status: updated just now, 4 of 5 sources OK")


def test_watch_status_ages_then_goes_stale(page, server):
    server.write_feed(build_feed(generated_at=NOW - timedelta(minutes=45)))
    open_dashboard(page, server)
    expect(page.locator("#watch-btn")).to_have_attribute("data-state", "aging")
    expect(page.locator("#watch-flag")).to_have_text("Late")
    expect(page.locator("#watch-btn")).to_have_attribute(
        "aria-label", "Feed status: running late, updated 45 min ago, 4 of 5 sources OK"
    )
    expect(page.locator("#stale-banner")).to_be_hidden()

    server.write_feed(build_feed(generated_at=NOW - timedelta(hours=3)))
    page.reload()
    expect(page.locator("#watch-btn")).to_have_attribute("data-state", "stale")
    expect(page.locator("#watch-flag")).to_have_text("Stale")
    expect(page.locator("#stale-banner")).to_be_visible()


def test_watch_panel_explains_status_and_closes_with_escape(page, server):
    open_dashboard(page, server)
    watch = page.locator("#watch-btn")
    watch.click()
    panel = page.get_by_role("region", name="Feed status")
    expect(watch).to_have_attribute("aria-expanded", "true")
    expect(panel).to_contain_text("Watching: the feed is up to date.")
    expect(panel).to_contain_text("4 of 5 answered")
    expect(panel).to_contain_text("Sample Security News")
    expect(panel).to_contain_text("HTTP 403")
    page.keyboard.press("Escape")
    expect(panel).to_be_hidden()
    assert page.evaluate("document.activeElement.id") == "watch-btn"


def test_search_matches_are_highlighted_apart_from_watchlist_terms(page, server):
    open_dashboard(page, server)
    page.get_by_role("searchbox").fill('"supply chain"')
    title = item(page, "Supply chain intrusion").locator(".item-title")
    expect(title.locator("mark.hl-search")).to_have_text("Supply chain")
    expect(page.locator("#active-filters")).to_contain_text('Search: "supply chain"')
    expect(page.locator(".filters-tip")).to_have_count(0)
    expect(page.locator("#announcer")).to_have_text("1 item match")

    page.get_by_role("searchbox").fill("supply chain")
    expect(page.locator(".filters-tip")).to_have_text('Tip: "supply chain" in quotes matches those words together')


def test_view_changes_are_announced(page, server):
    open_dashboard(page, server)
    page.locator('[data-view="unread"]').click()
    expect(page.locator("#announcer")).to_have_text(f"Unread: {len(ITEMS)} items")
    expect(page.locator("#status")).to_be_hidden()  # spoken only; the feed itself is the visible result


def test_source_groups_fold_away_unless_something_needs_attention(page, server):
    open_dashboard(page, server)
    cert_group = page.locator(".source-group", has=page.locator(".source-row", has_text="Sample CERT"))
    failing_group = page.locator(".source-group", has=page.locator(".source-row", has_text="Sample Security News"))
    expect(cert_group).not_to_have_attribute("open", "")
    expect(failing_group).to_have_attribute("open", "")  # a source is failing: never folded away
    cert_group.locator("summary").click()
    expect(page.get_by_role("checkbox", name="Sample CERT")).to_be_visible()
    page.get_by_role("checkbox", name="Geopolitics").uncheck()  # re-renders the sidebar
    expect(cert_group).to_have_attribute("open", "")  # the reader's choice survives


def test_skip_link_jumps_to_the_timeline(page, server):
    open_dashboard(page, server)
    page.keyboard.press("Tab")
    expect(page.get_by_role("link", name="Skip to timeline")).to_be_focused()
    page.keyboard.press("Enter")
    assert page.evaluate("document.activeElement.closest('article')?.dataset.id") == "i01"


def test_keyboard_shortcuts_move_save_and_mark(page, server):
    open_dashboard(page, server)
    page.keyboard.press("j")
    assert page.evaluate("document.activeElement.closest('article')?.dataset.id") == "i01"
    page.keyboard.press("j")
    second = page.evaluate("document.activeElement.closest('article')?.dataset.id")
    assert second != "i01"
    page.keyboard.press("s")
    expect(page.locator(f'article[data-id="{second}"] [data-action="save"]')).to_have_attribute("aria-pressed", "true")
    page.keyboard.press("m")
    expect(page.locator(f'article[data-id="{second}"]')).to_have_class(re.compile(r"\bis-read\b"))
    assert page.evaluate("document.activeElement.closest('article')?.dataset.id") == second
    page.keyboard.press("k")
    assert page.evaluate("document.activeElement.closest('article')?.dataset.id") == "i01"
    with page.expect_popup():
        page.keyboard.press("o")
    expect(page.locator('article[data-id="i01"]')).to_have_class(re.compile(r"\bis-read\b"))


def test_shortcuts_ignore_typing_and_question_mark_opens_help(page, server):
    open_dashboard(page, server)
    page.get_by_role("searchbox").fill("j")
    expect(page.locator("article.item").first).to_be_visible()
    assert page.evaluate("document.activeElement.id") == "search"
    page.get_by_role("searchbox").press("Escape")
    page.evaluate("document.activeElement.blur()")
    page.keyboard.press("?")
    help_dialog = page.get_by_role("dialog", name="Keyboard shortcuts")
    expect(help_dialog).to_be_visible()
    expect(help_dialog).to_contain_text("won’t find APT28")
    page.keyboard.press("Escape")
    expect(help_dialog).to_be_hidden()
    page.get_by_role("button", name="Shortcuts").click()
    expect(help_dialog).to_be_visible()


def test_a_stamped_site_loads_every_module(page, server):
    from owlfeed.stamp import stamp_site

    version = stamp_site(server.root)
    requests = []
    page.on("request", lambda request: requests.append(request.url))
    open_dashboard(page, server)
    scripts = [url for url in requests if url.endswith(".js") or ".js?v=" in url]
    assert scripts and all(url.endswith(f"?v={version}") for url in scripts), scripts
    page.get_by_role("searchbox").fill("ransomware")
    expect(page.locator("article.item mark.hl-search").first).to_be_visible()  # filters.js loaded


def test_prefix_watch_terms_catch_longer_words(page, server):
    open_dashboard(page, server)
    page.get_by_role("textbox", name="Add a watchlist term").fill("Exampl*")
    page.get_by_role("textbox", name="Add a watchlist term").press("Enter")
    expect(page.locator(".chip-label")).to_have_text(["Exampl*"])
    expect(page.locator("article.is-watch").first).to_be_visible()
    expect(page.locator("#watch-hint")).to_be_visible()  # the match rule stays on screen


def test_only_opens_just_the_group_it_affects_and_clear_folds_it_again(page, server):
    open_dashboard(page, server)
    cert = page.locator(".source-group", has=page.locator(".source-row", has_text="Sample CERT"))
    cert.locator("summary").click()
    page.get_by_role("button", name="Show only Sample CERT").click()
    research = page.locator(".source-group", has=page.locator(".source-row", has_text="Sample Threat Research"))
    expect(research).not_to_have_attribute("open", "")  # all off: its "0/1" tally says it all
    expect(research.locator(".group-tally")).to_have_text("0/1")
    page.locator("#active-filters").get_by_role("button", name="Remove filter: Only Sample CERT").click()
    expect(research).not_to_have_attribute("open", "")
    expect(cert).to_have_attribute("open", "")  # the reader opened this one
    # Only the failing group is open by itself.
    assert page.evaluate("[...document.querySelectorAll('.source-group[open]')].length") == 2


def test_hidden_categories_show_zero_sources(page, server):
    open_dashboard(page, server)
    page.get_by_role("checkbox", name="Geopolitics").uncheck()
    world = page.locator(".source-group", has=page.locator(".source-row", has_text="Sample World Desk"))
    expect(world.locator(".group-tally")).to_have_text("0/1")


def test_item_actions_speak_and_the_cursor_row_is_marked(page, server):
    open_dashboard(page, server)
    page.keyboard.press("j")
    assert page.evaluate("getComputedStyle(document.activeElement.closest('article')).backgroundColor") != page.evaluate(
        "getComputedStyle(document.querySelectorAll('article')[1]).backgroundColor"
    )
    page.keyboard.press("s")
    expect(page.locator("#announcer")).to_have_text("Saved")
    page.keyboard.press("m")
    expect(page.locator("#announcer")).to_have_text("Marked as read")
    page.keyboard.press("m")
    expect(page.locator("#announcer")).to_have_text("Marked as unread")


def test_number_keys_switch_views(page, server):
    open_dashboard(page, server)
    page.keyboard.press("3")
    expect(page.locator('[data-view="unread"]')).to_have_attribute("aria-current", "true")
    page.keyboard.press("1")
    expect(page.locator('[data-view="all"]')).to_have_attribute("aria-current", "true")


def test_mark_all_hands_keyboard_focus_to_undo(page, server):
    open_dashboard(page, server)
    page.locator("#mark-all-read").focus()
    page.keyboard.press("Enter")
    expect(page.locator("#status-action")).to_be_focused()
    page.keyboard.press("Enter")
    expect(page.locator('[data-view="unread"] .count')).to_have_text(str(len(ITEMS)))


def test_watch_badges_name_themselves_and_the_drawer_is_a_dialog(make_page, server):
    page = make_page(viewport=(390, 800))
    page.clock.set_fixed_time(NOW)
    open_dashboard(page, server)
    page.get_by_role("button", name="Open views and filters").click()
    expect(page.get_by_role("dialog", name="Views and filters")).to_be_visible()
    page.get_by_role("textbox", name="Add a watchlist term").fill("ExampleVPN")
    page.get_by_role("textbox", name="Add a watchlist term").press("Enter")
    page.get_by_role("button", name="Close menu").click()
    expect(page.locator("#sidebar")).not_to_have_attribute("role", "dialog")
    expect(page.locator(".badge-watch").first).to_have_text("Watchlist: ExampleVPN")


def test_search_uses_whole_words_like_the_watchlist(page, server):
    open_dashboard(page, server)
    search = page.get_by_role("searchbox")
    search.fill("Examp")
    # No whole-word match, so the prefix form runs, and says so...
    expect(page.locator(".filters-widened")).to_contain_text("No whole-word matches for “Examp”, so showing Examp*")
    expect(page.locator("article.item").first).to_be_visible()
    # ...and "Search exactly" goes back to whole words: nothing, only inside longer words.
    page.locator(".filters-widened").get_by_role("button", name="Search exactly").click()
    expect(page.get_by_text("Nothing matches “Examp”")).to_be_visible()
    search.fill("Examp*")
    expect(page.locator("article.item").first).to_be_visible()
    expect(page.locator("mark.hl-search").first).to_have_text(re.compile(r"^Examp\w+"))


def test_empty_new_view_names_its_baseline_and_points_to_unread(page, server):
    set_last_visit(page, iso(NOW))  # nothing in the sample feed arrived after this
    open_dashboard(page, server)
    page.locator('[data-view="new"]').click()
    expect(page.get_by_text("Nothing new since the 2:00 PM update you last saw")).to_be_visible()
    expect(page.get_by_text(f"{len(ITEMS)} unread items from earlier are still waiting.")).to_be_visible()
    page.get_by_role("button", name="Go to Unread").click()
    expect(page.locator('[data-view="unread"]')).to_have_attribute("aria-current", "true")
    expect(page.locator("article.item")).to_have_count(len(ITEMS))


def test_status_vocabulary_is_spelled_out(page, server):
    open_dashboard(page, server)
    expect(page.locator(".watch-tally")).to_have_text("4/5 sources")
    page.locator("#watch-btn").click()
    legend = page.locator(".watch-legend")
    expect(legend).to_contain_text("Late")
    expect(legend).to_contain_text("Stale")
    expect(legend).to_contain_text("4/5")
    news = page.locator(".source-group", has=page.locator(".source-row", has_text="Sample Security News"))
    expect(news.get_by_role("checkbox", name=re.compile(r"^Sample Security News ?, not answering: Last refresh failed: HTTP 403"))).to_be_attached()
    cert = page.locator(".source-row", has_text="Sample CERT")
    expect(cert.locator(".sr-only")).to_have_text(", answering")


def test_phone_top_bar_leaves_room_for_status_and_search(make_page, server):
    page = make_page(viewport=(390, 800))
    page.clock.set_fixed_time(NOW)
    open_dashboard(page, server)
    expect(page.locator("#theme-btn")).to_be_hidden()
    assert page.evaluate("getComputedStyle(document.getElementById('search')).fontSize") == "16px"
    page.get_by_role("button", name="Open views and filters").click()
    page.locator("#theme-btn-drawer").click()
    assert page.evaluate("document.documentElement.dataset.theme") == "dark"
    expect(page.locator("#theme-btn-drawer")).to_have_text("Light mode")


def test_the_watchlist_view_drops_the_wash(page, server):
    open_dashboard(page, server)
    page.get_by_role("textbox", name="Add a watchlist term").fill("ExampleVPN")
    page.get_by_role("textbox", name="Add a watchlist term").press("Enter")
    hit = page.locator("article.is-watch").first
    washed = hit.evaluate("el => getComputedStyle(el).backgroundColor")
    page.locator('[data-view="watchlist"]').click()
    plain = page.locator("article.is-watch").first.evaluate("el => getComputedStyle(el).backgroundColor")
    assert washed != plain
    expect(page.locator("article.is-watch .badge-watch").first).to_be_visible()


def test_category_checkboxes_agree_with_source_filters(page, server):
    open_dashboard(page, server)
    cyber = page.get_by_role("checkbox", name=re.compile(r"^Cyber"))
    geo = page.get_by_role("checkbox", name=re.compile(r"^Geopolitics"))
    page.locator(".source-group", has=page.locator(".source-row", has_text="Sample CERT")).locator("summary").click()
    page.get_by_role("button", name="Show only Sample CERT").click()
    expect(geo).not_to_be_checked()
    # Hidden: the muted count says what showing it would add, never a bare 0.
    expect(page.locator(".check-row", has=geo).locator(".count")).to_have_text(re.compile(r"^[1-9]\d* hidden$"))
    assert page.evaluate("document.querySelector('[data-category=\"Cyber\"]').indeterminate")
    cyber.click()  # "show all of Cyber"
    expect(cyber).to_be_checked()
    assert not page.evaluate("document.querySelector('[data-category=\"Cyber\"]').indeterminate")
    expect(page.locator(".item-source", has_text="Sample Threat Research").first).to_be_visible()
    geo.click()
    expect(page.locator("article.item")).to_have_count(len(ITEMS))


def test_stale_banner_speaks_to_readers_and_can_be_hidden(page, server):
    server.write_feed(build_feed(generated_at=NOW - timedelta(hours=3)))
    open_dashboard(page, server)
    banner = page.locator("#stale-banner")
    expect(banner).to_contain_text("Newer reporting may be missing.")
    expect(banner).not_to_contain_text("Actions")  # the owner's fix lives in the watch report
    page.get_by_role("button", name="Hide for now").click()
    expect(banner).to_be_hidden()
    expect(page.locator("#watch-btn")).to_be_focused()
    expect(page.locator("#watch-flag")).to_have_text("Stale")  # the chip keeps saying it
    page.reload()
    expect(page.locator("article.item").first).to_be_visible()
    expect(banner).to_be_hidden()  # hidden for this build, for the rest of the session
    page.locator("#watch-btn").click()
    expect(page.locator(".watch-owner")).to_contain_text("Refresh feed")


def test_zero_result_search_offers_the_prefix_version(page, server):
    open_dashboard(page, server)
    page.get_by_role("searchbox").fill("Examp")
    page.get_by_role("button", name="Search exactly").click()  # opt out of the automatic prefix form
    expect(page.get_by_text("Nothing matches “Examp” as whole words")).to_be_visible()
    expect(page.locator("#mark-all-read")).to_have_text("Nothing to mark")  # not "All read"
    page.get_by_role("button", name="Search Examp*").click()
    expect(page.get_by_role("searchbox")).to_have_value("Examp*")
    expect(page.locator("article.item").first).to_be_visible()
    assert page.evaluate("document.activeElement.closest('article') !== null"), page.evaluate("document.activeElement.outerHTML.slice(0, 80)")
    expect(page.locator("#announcer")).to_contain_text("match")


def test_adding_a_listed_watch_term_says_so(page, server):
    open_dashboard(page, server)
    field = page.get_by_role("textbox", name="Add a watchlist term")
    field.fill("ExampleVPN")
    field.press("Enter")
    field.fill("examplevpn")
    field.press("Enter")
    expect(field).to_have_value("examplevpn")  # kept, not silently cleared
    expect(page.locator("#announcer")).to_have_text("ExampleVPN is already on your watchlist")
    expect(page.locator(".chip.is-flash")).to_have_count(1)
    expect(page.locator(".chip-label")).to_have_text(["ExampleVPN"])


def test_new_view_never_reads_as_all_clear_while_stale(page, server):
    server.write_feed(build_feed(generated_at=NOW - timedelta(hours=3)))
    set_last_visit(page, iso(NOW))
    open_dashboard(page, server)
    page.locator('[data-view="new"]').click()
    expect(page.get_by_text("No refresh since 11:00 AM")).to_be_visible()
    expect(page.get_by_text("can’t confirm there’s nothing new", exact=False)).to_be_visible()
    expect(page.get_by_text("Nothing new since")).to_have_count(0)
    expect(page.get_by_text("That was 3 hours ago.", exact=False)).to_be_visible()
    expect(page.get_by_role("button", name="Show Unread, newest first")).to_be_visible()


def test_stale_new_view_names_the_day_once_it_is_older_than_today(page, server):
    server.write_feed(build_feed(generated_at=NOW - timedelta(days=3)))
    set_last_visit(page, iso(NOW))
    open_dashboard(page, server)
    page.locator('[data-view="new"]').click()
    # NOW is a Thursday: three days earlier is Monday, so a bare clock time would be ambiguous.
    expect(page.locator(".empty-title")).to_have_text("No refresh since Mon 2:00 PM")
    expect(page.get_by_text("That was 3 days ago.", exact=False)).to_be_visible()


def test_a_search_a_view_hides_points_to_all_items(page, server):
    open_dashboard(page, server)
    page.locator("article.item").first.get_by_role("button", name="Save for later").click()  # something saved, but not this
    page.locator('[data-view="saved"]').click()
    page.fill("#search", "Weekly vulnerability")
    expect(page.locator(".empty-title")).to_have_text("Nothing in Saved matches “Weekly vulnerability”")
    expect(page.locator(".empty-detail")).to_contain_text("in All items")
    expect(page.get_by_text("Check the spelling")).to_have_count(0)
    page.get_by_role("button", name="Search all items").click()
    expect(page.locator(TITLES)).to_have_text(["Weekly vulnerability summary"])
    expect(page.locator('.view-btn[data-view="all"]')).to_have_attribute("aria-current", "true")


def test_keyboard_cursor_shows_in_every_view(page, server):
    open_dashboard(page, server)
    page.get_by_role("textbox", name="Add a watchlist term").fill("Example*")
    page.get_by_role("textbox", name="Add a watchlist term").press("Enter")
    page.evaluate("document.activeElement.blur()")
    for view in ("1", "5"):  # All items, then Watchlist hits
        page.keyboard.press(view)
        page.keyboard.press("j")
        focused = page.evaluate("getComputedStyle(document.activeElement.closest('article')).backgroundColor")
        rest = page.evaluate(
            "getComputedStyle([...document.querySelectorAll('article')].find(a => !a.contains(document.activeElement))).backgroundColor"
        )
        assert focused != rest, (view, focused, rest)
        page.evaluate("document.activeElement.blur()")


def test_suggestion_from_the_keyboard_keeps_focus_in_the_results(page, server):
    open_dashboard(page, server)
    page.get_by_role("searchbox").fill("Examp")
    page.get_by_role("button", name="Search exactly").click()
    page.get_by_role("button", name="Search Examp*").focus()
    page.keyboard.press("Enter")
    expect(page.get_by_role("searchbox")).to_have_value("Examp*")
    assert page.evaluate("document.activeElement.closest('article') !== null"), page.evaluate("document.activeElement.tagName")


def test_filter_tokens_remove_one_constraint_and_keep_the_rest(page, server):
    open_dashboard(page, server)
    page.get_by_role("checkbox", name="Geopolitics").uncheck()
    page.get_by_role("searchbox").fill("Example*")
    bar = page.locator("#active-filters")
    expect(bar.get_by_role("button", name="Clear all")).to_be_visible()
    bar.get_by_role("button", name="Remove filter: Search: Example*").press("Enter")
    expect(page.get_by_role("searchbox")).to_have_value("")
    expect(page.get_by_role("checkbox", name="Geopolitics")).not_to_be_checked()  # the category filter stays
    expect(bar.get_by_role("button", name="Clear all")).to_have_count(0)  # one token left: its × is enough
    assert page.evaluate("document.activeElement.dataset.clearFilter") == "categories"


def test_watchlist_chip_filters_to_one_terms_hits(page, server):
    open_dashboard(page, server)
    page.get_by_label("Add a watchlist term").fill("Example*")
    page.get_by_label("Add a watchlist term").press("Enter")
    page.get_by_label("Add a watchlist term").fill("ransomware")
    page.get_by_label("Add a watchlist term").press("Enter")
    chip = page.locator("[data-watch-term='ransomware']")
    expect(chip).to_have_attribute("aria-label", re.compile(r"^ransomware: \d+ hits?$"))
    hits = int(chip.locator(".chip-count").inner_text())
    chip.click()
    expect(chip).to_have_attribute("aria-pressed", "true")
    expect(page.locator("article.item")).to_have_count(hits)
    expect(page.locator("#active-filters")).to_contain_text("Term: ransomware")
    chip.click()  # pressed again: all watchlist hits
    expect(chip).to_have_attribute("aria-pressed", "false")
    expect(page.locator("#active-filters")).not_to_contain_text("Term:")


def test_compact_rows_hide_summaries_and_persist(page, server):
    open_dashboard(page, server)
    expect(page.locator(".item-summary").first).to_be_visible()
    page.keyboard.press("d")
    expect(page.locator("#feed")).to_have_attribute("data-density", "compact")
    expect(page.locator("#density-btn")).to_have_attribute("aria-pressed", "true")
    expect(page.locator(".item-summary").first).to_be_hidden()
    page.reload()
    expect(page.locator("#feed")).to_have_attribute("data-density", "compact")


def test_sidebar_counts_follow_the_search(page, server):
    open_dashboard(page, server)
    all_count = page.locator('[data-view="all"] .count')
    expect(all_count).to_have_text(str(len(ITEMS)))
    page.get_by_role("searchbox").fill("Example*")
    expect(page.locator("#sidebar")).to_have_class(re.compile(r"\bis-searching\b"))  # the debounce has fired
    shown = page.locator("article.item").count()
    assert 0 < shown < len(ITEMS)  # the search really narrowed the list
    expect(all_count).to_have_text(str(shown))


def test_empty_state_names_and_lifts_the_hiding_filter(page, server):
    open_dashboard(page, server)
    page.get_by_role("checkbox", name="Geopolitics").uncheck()
    page.get_by_role("searchbox").fill("World*")
    lift = page.get_by_role("button", name="Show Geopolitics too")
    expect(page.locator(".empty")).to_contain_text("hidden by the category filter")
    lift.click()
    expect(page.locator("article.item").first).to_be_visible()
    expect(page.get_by_role("searchbox")).to_have_value("World*")  # the search stays


def test_briefing_views_lead_with_hits_and_end_with_a_finish_line(page, server):
    open_dashboard(page, server)
    page.get_by_label("Add a watchlist term").fill("ExampleVPN")
    page.get_by_label("Add a watchlist term").press("Enter")
    page.locator('[data-view="unread"]').click()
    pinned = page.locator(".day-pinned")
    expect(pinned.locator(".day-title")).to_have_text("Watchlist hits")
    expect(pinned.locator("article.is-watch").first).to_be_visible()
    # Every hit is in the pinned section, not repeated in the timeline below.
    assert page.locator(".day:not(.day-pinned) article.is-watch").count() == 0
    expect(page.locator(".briefing")).to_contain_text("watchlist hit")
    expect(page.locator(".caught-up")).to_be_visible()
    page.locator('[data-view="all"]').click()  # All keeps strict time order
    expect(page.locator(".day-pinned")).to_have_count(0)


def test_briefing_ends_with_a_scoped_mark_read_and_only_then_says_caught_up(page, server):
    open_dashboard(page, server)
    page.locator('[data-view="unread"]').click()
    end = page.locator(".caught-up")
    expect(end).to_contain_text(f"{len(ITEMS)} unread items")
    end.get_by_role("button", name=f"Mark these {len(ITEMS)} read").click()
    expect(page.get_by_text("You're all caught up")).to_be_visible()
    expect(page.locator("#status").get_by_role("button", name="Undo")).to_be_visible()


def test_a_whole_word_term_offers_its_prefix_form_when_that_catches_more(page, server):
    open_dashboard(page, server)
    page.get_by_label("Add a watchlist term").fill("Example")
    page.get_by_label("Add a watchlist term").press("Enter")
    upgrades = page.locator("#watch-upgrades")
    expect(upgrades).to_contain_text("1 term could catch more")  # one quiet line, not an offer per chip
    upgrades.get_by_role("button", name="Review").click()
    offer = page.locator("[data-upgrade-term='Example']")
    expect(offer).to_have_text(re.compile(r"^Example → Example\* \+\d+$"))
    offer.click()
    expect(page.locator("[data-watch-term='Example*']")).to_be_focused()
    expect(page.locator("[data-upgrade-term]")).to_have_count(0)
    expect(upgrades).to_be_hidden()


def test_briefing_summary_counts_are_filters(page, server):
    open_dashboard(page, server)
    page.locator('[data-view="unread"]').click()
    summary = page.get_by_role("list", name="Briefing summary")
    summary.get_by_role("button", name=re.compile(r"Cyber$")).click()
    expect(page.get_by_role("checkbox", name="Geopolitics")).not_to_be_checked()
    expect(page.locator('[data-view="unread"]')).to_have_attribute("aria-current", "true")  # still the briefing


def test_removing_a_watch_term_can_be_undone_in_place(page, server):
    open_dashboard(page, server)
    field = page.get_by_role("textbox", name="Add a watchlist term")
    for term in ["ExampleVPN", "ransomware", "ExampleOS"]:
        field.fill(term)
        field.press("Enter")
    expect(page.locator("#announcer")).to_contain_text("ExampleOS added to your watchlist")
    page.get_by_role("button", name="Remove ransomware from watchlist").click()
    expect(page.locator(".chip-label")).to_have_text(["ExampleVPN", "ExampleOS"])
    page.locator("#status").get_by_role("button", name="Undo").click()
    expect(page.locator(".chip-label")).to_have_text(["ExampleVPN", "ransomware", "ExampleOS"])  # back in its place


def test_briefing_views_carry_their_name_and_keep_the_stale_banner(page, server):
    server.write_feed(build_feed(generated_at=NOW - timedelta(hours=3)))
    open_dashboard(page, server)
    page.locator('[data-view="unread"]').click()
    expect(page.locator("#active-filters")).to_be_hidden()  # no view token: the summary names the view
    expect(page.locator("#stale-banner")).to_be_visible()  # a briefing is where trust matters most
    page.locator('[data-view="all"]').click()
    expect(page.locator("#stale-banner")).to_be_visible()


def test_briefing_hits_count_opens_the_hits_in_place(page, server):
    open_dashboard(page, server)
    for term in ["Example*", "ransomware", "summit", "port", "flaw", "kit"]:
        page.get_by_label("Add a watchlist term").fill(term)
        page.get_by_label("Add a watchlist term").press("Enter")
    page.locator('[data-view="unread"]').click()
    hits = page.locator(".briefing").get_by_role("button", name=re.compile(r"watchlist hits$"))
    total = int(hits.locator("strong").inner_text())
    assert total > 5
    hits.click()
    expect(page.locator('[data-view="unread"]')).to_have_attribute("aria-current", "true")  # still the briefing
    expect(page.locator(".day-pinned article")).to_have_count(total)


def test_a_match_past_the_visible_lines_is_shown_as_a_snippet(page, server):
    open_dashboard(page, server)
    page.get_by_role("searchbox").fill("certificates")
    summary = page.locator("article.item .item-summary").first
    expect(summary).to_have_class(re.compile(r"\bis-snippet\b"))
    expect(summary).to_have_text(re.compile(r"^…"))
    expect(summary.locator("mark.hl-search")).to_have_text("certificates")


def test_phone_tab_bar_switches_views_and_rows_start_comfortable(make_page, server):
    page = make_page(viewport=(390, 844))
    page.clock.set_fixed_time(NOW)
    open_dashboard(page, server)
    # No density chosen yet: a phone starts comfortable, like wider screens.
    expect(page.locator("#feed")).to_have_attribute("data-density", "comfortable")
    tabbar = page.locator("#tabbar")
    expect(tabbar).to_be_visible()
    expect(page.locator("#menu-btn")).to_be_hidden()
    tabbar.locator('[data-tab="unread"]').click()
    expect(tabbar.locator('[data-tab="unread"]')).to_have_attribute("aria-current", "true")
    expect(page.locator('.view-btn[data-view="unread"]')).to_have_attribute("aria-current", "true")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_wide_screens_keep_comfortable_rows_and_no_tab_bar(page, server):
    open_dashboard(page, server)
    expect(page.locator("#feed")).to_have_attribute("data-density", "comfortable")
    expect(page.locator("#tabbar")).to_be_hidden()


def test_a_module_that_fails_to_load_shows_a_reload_message(page, server):
    # An older or missing copy of one module stops the app: the page says so instead of "Loading…".
    page.route("**/js/render.js*", lambda route: route.abort())
    page.goto(server.url)
    expect(page.locator(".empty-title", has_text="Owlfeed couldn’t start")).to_be_visible()
    expect(page.locator("#feed")).to_have_attribute("aria-busy", "false")
    expect(page.get_by_role("button", name="Reload")).to_be_visible()
    page.js_errors.clear()  # the failed load is the point of this test


def test_a_started_app_never_shows_the_failure_message(page, server):
    page.clock.install()
    open_dashboard(page, server)
    assert page.evaluate("document.documentElement.dataset.app") == "ready"
    page.clock.run_for(11_000)  # past the watchdog's grace period
    expect(page.locator(".empty-title", has_text="Owlfeed couldn’t start")).to_have_count(0)


def test_saved_view_says_when_filters_hide_saved_items(page, server):
    open_dashboard(page, server)
    page.locator("article.item", has=page.locator(".item-source", has_text="Sample CERT")).first.get_by_role("button", name="Save for later").click()
    page.locator("article.item", has=page.locator(".item-source", has_text="Sample World Desk")).first.get_by_role("button", name="Save for later").click()
    page.locator('[data-category="Geopolitics"]').uncheck()
    page.locator('.view-btn[data-view="saved"]').click()
    expect(page.locator("article.item")).to_have_count(1)
    note = page.locator("#active-filters .filters-widened")
    expect(note).to_contain_text("1 saved item hidden by your filters")
    note.get_by_role("button", name="Show them").click()
    expect(page.locator("article.item")).to_have_count(2)


def test_failed_first_load_retries_on_its_own(make_page, server):
    server.remove_feed()
    page = make_page()
    page.clock.install(time=NOW)
    page.goto(server.url)
    expect(page.get_by_text("No feed data published yet")).to_be_visible()
    server.write_feed(build_feed())
    page.clock.run_for(61_000)  # RETRY_MS in app.js
    expect(page.locator("article.item").first).to_be_visible()


def test_restore_applies_the_backed_up_density_at_once(page, server, tmp_path):
    backup = tmp_path / "backup.json"
    backup.write_text(
        '{"app": "owlfeed", "version": 1, "prefs": {"view": "all", "density": "compact"}}', encoding="utf-8"
    )
    open_dashboard(page, server)
    expect(page.locator("#feed")).to_have_attribute("data-density", "comfortable")
    page.locator("#import-input").set_input_files(str(backup))
    expect(page.locator("#feed")).to_have_attribute("data-density", "compact")
    expect(page.locator("#density-btn")).to_have_attribute("aria-pressed", "true")


def test_another_tabs_prefs_are_picked_up_not_overwritten(page, server):
    open_dashboard(page, server)
    other = page.context.new_page()
    other.clock.set_fixed_time(NOW)
    open_dashboard(other, server)
    other.keyboard.press("d")
    expect(page.locator("#feed")).to_have_attribute("data-density", "compact")
    # A save from the first tab now keeps the other tab's density instead of reverting it.
    page.get_by_role("checkbox", name="Geopolitics").uncheck()
    stored = page.evaluate("JSON.parse(localStorage.getItem('owlfeed:v1:prefs')).density")
    assert stored == "compact"


def test_shortcuts_still_work_after_ticking_a_checkbox(page, server):
    open_dashboard(page, server)
    page.get_by_role("checkbox", name="Geopolitics").uncheck()
    page.keyboard.press("d")
    expect(page.locator("#feed")).to_have_attribute("data-density", "compact")


def test_phone_freshness_label_uses_short_ages(make_page, server):
    server.write_feed(build_feed(generated_at=NOW - timedelta(minutes=9)))
    page = make_page(viewport=(390, 844))
    page.clock.set_fixed_time(NOW)
    open_dashboard(page, server)
    expect(page.locator("#watch-short")).to_have_text("9m ago")


def unread_dot(page, row):
    return row.locator(".item-title").evaluate("el => getComputedStyle(el, '::before').content")


def test_read_rows_fade_and_drop_their_new_badge_without_dots(page, server):
    set_last_visit(page, iso(NOW - timedelta(minutes=100)))
    open_dashboard(page, server)
    rows = page.locator("article.item")
    new_row = rows.filter(has=page.locator(".badge-new")).first
    older_row = rows.filter(has_not=page.locator(".badge-new")).first
    # Unread vs read is told by the headline's ink and weight: no per-row dot.
    assert unread_dot(page, new_row) == "none"
    assert unread_dot(page, older_row) == "none"
    weight = lambda row: row.locator(".item-title a").evaluate("el => getComputedStyle(el).fontWeight")
    assert weight(new_row) == "650"
    new_row.get_by_role("button", name="Mark as read").click()
    expect(new_row.locator(".badge-new")).to_be_hidden()  # read: NEW goes with it
    assert weight(new_row) == "550"


def test_forced_colors_tell_dots_apart_by_shape(browser, server):
    context = browser.new_context(viewport={"width": 1280, "height": 900}, forced_colors="active", locale="en-US", timezone_id="UTC")
    page = context.new_page()
    page.clock.set_fixed_time(NOW)
    open_dashboard(page, server)
    radius = lambda sel: page.locator(sel).first.evaluate("el => getComputedStyle(el).borderRadius")
    colour = lambda sel: page.locator(sel).first.evaluate("el => getComputedStyle(el).backgroundColor")
    assert radius(".cat-dot.cat-cyber") != radius(".cat-dot.cat-geopolitics")  # round vs rounded square
    assert colour(".cat-dot.cat-cyber") == colour(".cat-dot.cat-geopolitics") == "rgb(0, 0, 0)"  # system colour, not the palette
    error_dot = page.locator(".health-dot.is-error").first
    assert error_dot.evaluate("el => getComputedStyle(el).borderTopWidth") == "2px"  # a failing source is a hollow ring
    context.close()


def test_phone_view_token_goes_when_a_tab_names_the_view(make_page, server):
    page = make_page(viewport=(390, 844))
    page.clock.set_fixed_time(NOW)
    open_dashboard(page, server)
    page.locator('#tabbar [data-tab="watchlist"]').click()
    expect(page.locator('#tabbar [data-tab="watchlist"]')).to_have_attribute("aria-current", "true")
    expect(page.locator('#active-filters [data-clear-filter="view"]')).to_have_count(0)  # the tab names it
    # Saved has no tab: its token stays, so the view is still named.
    page.get_by_role("button", name="Open views and filters").click()
    page.locator('.view-btn[data-view="saved"]').click()
    expect(page.locator('#active-filters [data-clear-filter="view"]')).to_have_count(1)
    expect(page.locator("#tabbar [aria-current]")).to_have_count(0)
    page.set_viewport_size({"width": 1280, "height": 900})  # wider screens have no tab bar: the token returns
    page.locator('.view-btn[data-view="watchlist"]').click()
    expect(page.locator('#active-filters [data-clear-filter="view"]')).to_have_count(1)


def test_desktop_link_says_it_opens_shortcuts_and_labels(page, server):
    open_dashboard(page, server)
    page.get_by_role("button", name="Shortcuts & labels").click()
    expect(page.get_by_role("dialog")).to_contain_text("What the labels mean")
    expect(page.get_by_role("dialog")).to_contain_text("Keyboard shortcuts")


def test_phone_tab_names_the_watchlist_in_full(make_page, server):
    page = make_page(viewport=(320, 640))
    open_dashboard(page, server)
    expect(page.locator("#tabbar .tab-label")).to_have_text(["All", "New", "Unread", "Watchlist", "Filters"])
    assert page.evaluate("[...document.querySelectorAll('.tab-label')].every(l => l.scrollWidth <= l.parentElement.clientWidth)")


def test_single_key_shortcuts_can_be_turned_off(page, server):
    open_dashboard(page, server)
    page.keyboard.press("?")
    page.get_by_label("Single-key shortcuts").uncheck()
    page.keyboard.press("Escape")
    page.keyboard.press("d")
    expect(page.locator("#feed")).to_have_attribute("data-density", "comfortable")  # WCAG 2.1.4
    page.reload()
    page.keyboard.press("3")
    expect(page.locator('[data-view="all"]')).to_have_attribute("aria-current", "true")  # the choice is kept


def test_x_marks_read_and_moves_on_and_shift_a_marks_the_view(page, server):
    open_dashboard(page, server)
    page.keyboard.press("j")
    first = page.locator("article.item").first
    page.keyboard.press("x")
    expect(first).to_have_class(re.compile(r"\bis-read\b"))
    expect(page.locator("article.item").nth(1).locator(".item-title a")).to_be_focused()
    page.keyboard.press("Shift+A")
    expect(page.locator("#status")).to_contain_text("Marked")
    expect(page.locator("article.item:not(.is-read)")).to_have_count(0)


def test_stale_data_does_not_claim_healthy_sources(page, server):
    server.write_feed(build_feed(generated_at=NOW - timedelta(hours=3)))
    open_dashboard(page, server)
    expect(page.locator(".health-dot.is-ok")).to_have_count(0)  # unknown, not green
    expect(page.locator(".health-dot.is-unknown").first).to_be_attached()
    expect(page.locator("#watch-btn")).to_contain_text("at last sweep")
    expect(page).to_have_title("Stale · Owlfeed")
    page.locator("#watch-btn").click()
    expect(page.locator("#watch-panel")).to_contain_text("How they are doing now is unknown")
    page.locator("#watch-panel").get_by_role("button", name="Check now").click()
    expect(page.locator("#status")).to_contain_text("No newer update yet")
    expect(page.locator("#watch-panel")).to_be_visible()  # the redraw mid-click doesn't close it
    expect(page.locator("#watch-panel").get_by_role("button", name="Check now")).to_be_focused()


def test_mid_width_names_the_view_and_keeps_mark_read_words(make_page, server):
    page = make_page(viewport=(800, 900))
    page.clock.set_fixed_time(NOW)
    open_dashboard(page, server)
    expect(page.locator("#tabbar")).to_be_visible()
    expect(page.locator('#tabbar [data-tab="all"]')).to_have_attribute("aria-current", "true")
    expect(page.locator("#mark-all-read")).to_contain_text(re.compile(r"Mark \d+ read"))
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_theme_toggle_returns_to_following_the_system(page, server):
    open_dashboard(page, server)  # light system theme
    page.locator("#theme-btn").click()
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    page.locator("#theme-btn").click()
    expect(page.locator("html")).not_to_have_attribute("data-theme", re.compile(".+"))
