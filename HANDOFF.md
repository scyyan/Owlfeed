# Owlfeed — handoff from the cloud session

Owlfeed is a Feedly / Recorded Future–style OSINT news dashboard. A Python fetcher pulls
trusted RSS/Atom feeds every 15 minutes in GitHub Actions and writes `site/data/feed.json`.
A static dashboard on GitHub Pages lists the items newest first: title (opens the source in
a new tab), source's own summary underneath. There is no AI, no API key and no server.

This file records the state of the work and how it got there, so it can continue in a local
session. Delete it before (or after) merging if you don't want it in `main`.

## State at handoff

- **Branch:** `claude/osint-news-dashboard-p063rx`. Head is `b87ed1b`; nothing is merged and
  no pull request is open.
- **CI:** green on `b87ed1b`. That covers Python unit tests, JavaScript unit tests, Playwright
  browser tests and the live feed check, which reports **31/31 enabled sources healthy** from
  GitHub's network.
- **Local test counts:** 123 Python unit tests and 32 browser tests (155 in total under
  pytest), plus 28 Node tests.
- **Not done yet (only the repo owner can do these):**
  1. Make the repo public: *Settings → General → Danger Zone → Change visibility*.
  2. Turn on Pages: *Settings → Pages → Build and deployment → Source:* **GitHub Actions**.
  3. Merge the branch into `main`. The push starts the first refresh and deploy, and the site
     appears at https://scyyan.github.io/Owlfeed/.

## Decisions from the interview

| Topic | Decision |
|---|---|
| Focus | Cyber threat intel + geopolitics & conflict |
| Hosting | GitHub Pages; repo to be made public (Pages is free for public repos) |
| Summaries | Each source's own feed blurb, cleaned and trimmed (≈320 chars) — no AI |
| Extras | Filter & search, watchlist highlights, "new since last visit" + auto-refresh, read & saved items |
| World news | BBC World, Al Jazeera, Guardian World |
| History | 7 days |
| Layout | Feedly-style sidebar + feed; follows system light/dark with a toggle |

## Running it locally

```sh
python -m venv .venv && . .venv/bin/activate
pip install --require-hashes -r requirements.txt -r requirements-dev.txt

python -m owlfeed build                 # fetch every feed into site/data/feed.json
python -m owlfeed check --samples 3     # per-source health report (add --include-disabled)
python -m http.server -d site 8000      # open http://localhost:8000

python -m pytest --ignore=tests/e2e     # fetcher unit tests
npm test                                # dashboard unit tests (Node 22+, TZ=UTC is set by the script)
python -m playwright install chromium
python -m pytest tests/e2e              # browser tests (fixed sample feed + fake clock)
```

- `OWLFEED_CHROMIUM=/path/to/chrome` makes the browser tests use a specific Chromium binary.
- To add a dependency, edit `requirements*.in`, then run
  `pip-compile --generate-hashes --strip-extras <file>.in`. Both files are hash-pinned, and pip
  refuses to mix hashed and unhashed requirements.
- The cloud sandbox could not reach news sites, so the real feeds were verified only through
  CI's **Feed check** job. Locally you can run `python -m owlfeed check` directly.

## Architecture

```
sources.yml ─► owlfeed (Python) ─► site/data/feed.json ─► static dashboard (vanilla JS, ES modules)
                   ▲                                              │
  previous feed.json from the live Pages site (state)  ◄── GitHub Pages ◄─ refresh.yml every 15 min
```

The repo holds no state. Each refresh downloads the currently deployed
`feed.json?run=<id>`, merges fresh entries into it, prunes it to 7 days and redeploys.

- **404:** the run falls back to an artifact saved by the last successful *scheduled or push*
  run of `refresh.yml` on `main`. Without one, it starts empty.
- **Any other failure** (5xx, invalid JSON): the run exits with code 2, so the live site keeps
  its last good data.

### Python fetcher (`owlfeed/`)

| File | Role |
|---|---|
| `config.py` | Loads and validates `sources.yml`: unique ids, https feed URLs, declared categories/groups, valid `tz`. A `Source` has `id, name, feed, site, category, group, enabled, summary_from, exclude_title, tz`. |
| `fetch.py` | Concurrent GETs (8 threads), a descriptive UA, ETag/Last-Modified, one retry on 429/5xx/connection errors, a 10 MB cap, a 60 s per-download and 180 s overall wall-clock deadline (`read1` loop). |
| `parse.py` | feedparser (always fed `io.BytesIO`, never a path). Picks the link (`feedburner:origLink` first; guid only if it is an absolute http URL), cleans tracking params, sets `item_id = sha1(netloc+path+query)[:16]`. Parses dates in priority order with loose fallbacks (RFC 822 without a zone, fractional seconds, Drupal formats, named zones like CEST/BST, the source's `tz` for zone-less dates). Applies `exclude_title` and puts dated entries first. |
| `text.py` | HTML → plain paragraphs (stdlib `HTMLParser`). Handles double-escaped HTML, removes boilerplate and junk paragraphs, drops headings, truncates at a sentence end or a word boundary + "…". |
| `store.py` | Restores the previous state, merges, applies retention, writes tombstones for undated items, writes per-source health rows, writes the file atomically with mode 0644. |
| `__main__.py` | CLI. `build` exits 2 (previous state unreadable), 3 (all sources failed) or 4 (config error). `check` writes a Markdown job summary; feed text is fenced with `::stop-commands::` so it can't inject workflow commands. |

`feed.json` v1 has `{version, generated_at, retention_days, sources[], items[], expired{}}`:

- Each item is `{id, source, title, url, summary, published, first_seen, date_estimated}`.
- Undated items use `first_seen` as their date and get `date_estimated: true`; the UI shows a `~`.
- `expired` holds tombstones for undated items past 7 days: `{id: {source, since}}`.

### Dashboard (`site/`)

- No build step. A strict CSP meta tag allows only `'self'`: no inline script, no eval.
- All feed text is set with `textContent`, and only http(s) links are rendered.
- `app.js` is the controller (state, polling, visits, focus handling, drawer, export/import).
  `render.js` builds the DOM, rendering in chunks with IntersectionObserver.
- `filters.js`, `watchlist.js` and `time.js` are pure modules and have unit tests.
  `storage.js` wraps localStorage.
- **localStorage:** holds read/saved/watchlist/prefs/lastVisit/theme.
  - Writes are read-modify-write, and the `storage` event syncs other tabs.
  - When storage is blocked, the `memoryOnly` fallback keeps changes for the visit.
  - Saved items keep a full snapshot, so they outlive the 7-day window.
- **"New since last visit":** an item is new when its `first_seen` is later than the
  `generated_at` (server time) of the last build the reader saw. Reloads within 30 minutes
  keep the same baseline.
- **Auto-refresh:** polls every 5 minutes while the page is visible. At the top of the page,
  new items are applied directly; further down, an "↑ N new items" pill appears instead.

### Workflows (`.github/workflows/`)

- **`ci.yml`:** pytest, `npm test`, and Playwright with the bundled Chromium. Also runs an
  informational **Feed check** that checks every source, including disabled ones, from
  GitHub's network.
- **`refresh.yml`:** cron `4,19,34,49 * * * *`, plus push to `main` and manual runs.
  - The build job is read-only. It restores the 404 fallback artifact, best effort, then
    builds and uploads the artifact and the Pages bundle.
  - A separate deploy job holds `pages: write` and `id-token: write`.
- **`keepalive.yml`:** runs weekly and calls `gh api PUT …/enable` so GitHub doesn't pause the
  schedule after 60 inactive days. It skips workflows a person disabled by hand.

### Sources (`sources.yml`)

There are 31 enabled sources:

| Category | Group | Sources |
|---|---|---|
| Cyber | Government & CERT | CISA, NCSC UK, SANS ISC (Stormcast excluded) |
| Cyber | Threat research | Google Threat Intelligence, Microsoft, Talos, Unit 42, Securelist, ESET, Check Point, SentinelLabs, Sophos X-Ops, The DFIR Report (`summary_from: content`) |
| Cyber | Security news | The Record, BleepingComputer, Krebs, The Hacker News, SecurityWeek, Dark Reading, CyberScoop, Risky Bulletin |
| Geopolitics | Analysis & investigations | Bellingcat, Crisis Group (`tz: Europe/Brussels`; Arabic/Cyrillic titles excluded), DFRLab, Atlantic Council, Lowy Interpreter, Long War Journal, RUSI |
| Geopolitics | World news | BBC World, Al Jazeera, Guardian World |

- **Disabled but working**, one line to enable: Help Net Security, Infosecurity Magazine,
  Ars Security, Foreign Policy, War on the Rocks, Just Security, The Diplomat, Kyiv
  Independent, DW, France 24, UN News.
- **Dropped** because there's no usable feed from GitHub's network: ISW, Critical Threats,
  ACLED, CSIS. The README explains why.

## Bugs found and how they were fixed

Development ran in phases. Each phase was followed by multi-agent adversarial review rounds.
The confirmed findings per round were 45, then 65 (34 fixed), then 53 (28 fixed, 25 left
open), then 7, 3, 1 and 1. Every fix below has a regression test, and later fixes were
checked to fail on the code from before the fix.

### Early build bugs

- **Config test regex:** an unescaped `(s)` in a test regex acted as a regex group. Fixed with
  `re.escape`.
- **Title-repeat strip:** removing a repeated headline from the start of the summary let a
  title of "T" eat the start of "The". The strip now needs a whole-phrase match, `(?!\w)`.
- **`javascript:` guids:** these were joined into bogus URLs. Only absolute http(s) guids are
  accepted now.
- **feedparser deprecation warning:** fixed by reading keys with `dict.get(entry, key)`.
- **DFIR Report marketing block:**
  - A lazy match stopped at "Get in Touch", and a leading `\s*` glued words together.
  - Fixed by reordering the alternation, dropping the leading `\s*`, and running the heading
    pattern after the marketing pattern.
- **Second HTML pass leaked `</p></section>`.** In CDATA mode, HTMLParser treated text after a
  mentioned `<script>` as raw text. The second pass now runs with
  `CDATA_CONTENT_ELEMENTS = ()` (the `raw_text=False` flag).
- **`_read_limited` deadline was bound when the function was defined.** It is now read at
  call time.
- **Phone layout:** the `.sidebar-close` button showed on desktop. Fixed with a more specific
  CSS rule.
- **Browser tests under the fake clock:**
  - The CSP blocks `page.wait_for_function`, so the tests use a `wait_until` polling helper.
  - `mouse.wheel` stalls, so the tests scroll with `scrollTo`.
  - The toast expired before the assertion, so the tests advance the clock by 5 min + 1 s.
- **Item counts:** the new-items count included unusable (`javascript:`) items. Fixed with an
  `isUsable` check.

### Review round 1 (`eb753b8`): fetcher and workflow hardening

- **Response bodies:** feedparser could treat a response body as a local file path. It now
  always gets a byte stream.
- **Download time:** a download had no wall-clock cap. Each one now gets 60 s via a `read1`
  loop, and the whole fetch gets 3 minutes.
- **Bad entries:** one malformed entry or parser exception could sink a whole feed or the
  build. Errors are now caught per entry and per source.
- **Undated items coming back as NEW after 7 days:** these now get tombstones (more on
  tombstones below).
- **Zone-less dates:** they are read in the source's timezone, and more fallback date formats
  were added.
- **Feed text injecting workflow commands:** in CI logs, feed text could inject commands. The
  output is now fenced with `::stop-commands::`, and the job summary escapes Markdown.
- **Permissions:**
  - `feed.json` was written with mode 0600; it is now world-readable (0644).
  - `refresh.yml` was split into a read-only build job and a publish-only deploy job, and
    dependencies are hash-pinned.
- **Keepalive** no longer re-enables a refresh that someone disabled on purpose.

### Review round 2 (`9da8c48`): dashboard

- **Two open tabs overwrote each other's read/saved/watchlist data.** Storage now does
  read-modify-write and listens for `storage` events from other tabs.
- **"New since last visit"** compared against the client clock. It now compares against the
  server's `generated_at` of the last build the reader saw. It also resets after 30 minutes
  away, and updates still waiting behind the pill no longer advance it.
- **Saved items:**
  - Re-starring a saved item that had aged out of the feed failed. Fixed with an
    `unsavedSnapshots` map.
  - The pill and toast counted items hidden by filters.
- **Accessibility and layout:**
  - Keyboard focus was lost when the feed re-rendered.
  - The phone drawer was not inert or modal and didn't return focus.
  - Restore wasn't a real button.
  - Screen-reader announcements were missing.
  - Colours failed WCAG AA contrast.
  - Freshness and the stale-data warning were hidden on phones.

### Review round 3 (`a00f046`, `db07334`): closing gaps

- **Dates:**
  - A zone-less "updated" date outranked a proper "published" date.
  - Named zones (CEST, BST, JST) and fractional seconds didn't parse.
- **Titles:** feedparser's `text/plain` titles are now treated as plain text, so a headline
  about `<script>` keeps the word.
- **Broken links:** a broken channel or entry link emptied a whole source. Each candidate is
  now tried separately, with `source.site` as the fallback.
- **Tombstones:**
  - Normalized to UTC.
  - Future-dated or malformed ones are dropped, and so are ones whose `source` isn't a
    string (that used to crash with a TypeError).
  - Capped at `MAX_TOMBSTONES` = 5000.
  - The 30 days now count from the last time the feed listed the item.
  - Tombstones survive while a source returns 304 or fails.
- **Config:** categories and groups are declared in `sources.yml` and enforced, feeds must be
  https, and bad URLs give a clean config error.
- **`refresh.yml`:**
  - The 404 fallback used to live in the Actions cache, which other workflows can write. It
    is now an artifact from this workflow's own last successful run.
  - Looking it up is best effort: a `gh` failure no longer fails the run.
  - It only uses scheduled or push runs on `main`, since a manual run can start from any ref.
  - A partial download is deleted.
- **Dashboard:**
  - "Clear filters" opened the phone keyboard. It now focuses the newest item after a tap,
    and the search box from the keyboard.
  - Focus is kept when the last item in a view disappears.
  - The toast now has `pointer-events: none`, so it no longer blocks taps on Restore.
- **Tests:** `test_sources_file.py` no longer pins the exact category layout.
- **CI failure:** `test_restore_is_keyboard_operable` failed on CI's Chrome 156 headless shell,
  where Enter didn't report a native file chooser. The test now checks that Enter and Space
  ask the hidden file input to open. Opening the picker by click is still covered by
  `test_restore_from_the_phone_drawer_is_announced`.

### Rounds 4–7 (`79731be` → `b87ed1b`): fixes for regressions from earlier fixes

These were mostly the text-cleaning heuristics overshooting in one direction or the other.

- **Double-escaped HTML (`&lt;p&gt;…`).** The first decoding pass turns it into real markup,
  so there is a second pass. The final rules:
  - A paragraph is fully re-parsed only if it **opens** with a content tag or a complete
    comment, or **closes** a content tag.
  - Closed caption/script/style/form/svg/etc. elements are cut out whole (`_CLOSED_SKIP`,
    starting from the nearest opening tag) before that pass. A `<script>` mentioned earlier
    can't hide the rest of the text, and a `<` inside a script can't swallow it.
  - Otherwise only clearly stray void markup is removed:
    - Line-break runs glued to a word, a sentence end, a closing bracket or curly quote, or a
      straight quote that closes a word. Once one break in a paragraph qualifies, every break
      there counts (PHP `nl2br` output).
    - 1×1 tracking pixels.
    - `<!--more-->` / `<!-- wp: -->` comments between sentences.
  - Security write-ups that **quote** tags therefore keep every word: `allowed <p>, <br> and
    <hr>`, `such as "<br>"`, `("<br>", "<hr>")`, `<img src="https://…">`.
- **Plain-text titles:** they lose only a stray `<br>` and an `<img>` that has a quoted src
  and no `on…=` handler. An XSS-payload headline keeps its payload.
- **Truncation:**
  - Initials after acronyms ("CEO J. Smith") are not sentence ends.
  - A cut can happen before a lowercase product name (iOS, npm), but not at a quoted "?" or
    "!" mid-sentence, or after a lowercase abbreviation (a.m., et al., incl.).
  - The result never ends in ".…".
- **Tombstones and 304s:**
  - A 304 refreshes a tombstone only if its `since` ≥ the source's previous `last_ok`, which
    means the last good response still listed it.
  - That stops a short response after a month of 304s from reviving an item as new.
  - It also lets items the feed dropped expire after 30 days instead of piling up. In a
    simulated 180 days, the count holds at 27 rather than growing past 125.
- **Performance:** image-tag and break-run matching is linear now. Crafted inputs that took
  13–38 s per item take under 0.35 s.
- **Dashboard:**
  - Focus on the empty state now survives later refreshes; a refresh that brings items back
    focuses the first item.
  - Tests were added for the empty state without a button and for the active-filters Clear
    button.

### Known, accepted limitations

- In RSS, a single-escaped `&lt;br&gt;` in a description is a real line break, so prose
  written that way loses the tag. This is standard RSS semantics and was never handled
  differently.
- A short line with no closing punctuation (≤ 40 chars) is treated as a heading and dropped
  from summaries. This is long-standing behaviour.
- Code samples inside `<pre>` blocks come out garbled when a source uses
  `summary_from: content`. No current source summarises code.
- An Atom `<summary type="text">` that names `<script>` is cut at that word on the first pass.
- Truncation after a `?`/`!` followed by a lowercase product name falls back to a word-boundary
  cut. The review judged that the fix would cost more than it buys.

## Where to look when changing things

- **Summary looks wrong for a source:** test `owlfeed/text.py`. The pure entry points are
  `summary_text`, `make_summary`, `clean_title` and `truncate`. Add a case to
  `tests/test_text.py`; `tests/test_parse.py` runs whole feeds.
- **Source broken:** run `python -m owlfeed check --samples 3`, then fix `sources.yml`.
  `exclude_title`, `summary_from` and `tz` are per-source options.
- **Merge/retention/tombstones:** `owlfeed/store.py` `merge()`; tests are in
  `tests/test_store.py`.
- **UI behaviour:** `site/js/app.js`. Browser tests in `tests/e2e/test_dashboard.py` use the
  sample feed in `tests/e2e/sample_data.py`, with NOW fixed at 2026-10-15T14:00Z.
