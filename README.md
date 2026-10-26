# Owlfeed

An OSINT news dashboard in the spirit of Feedly or Recorded Future. Owlfeed pulls the latest
reporting from trusted cyber threat intelligence and geopolitical sources and lists it
newest first. Every item shows its headline with a short summary underneath, and clicking
the headline opens the original article in a new tab.

**Dashboard:** https://scyyan.github.io/Owlfeed/ (live after the one-time setup below)

## What you get

- **One timeline** of 31 sources, sorted by publication date and time and grouped by day,
  shown in your own time zone.
- **Summaries** taken from each source's own feed, cleaned of HTML, newsletter promos and
  "The post … appeared first on …" boilerplate, and trimmed to a few sentences.
- **Filters and search.** Narrow by category (Cyber, Geopolitics), by source (or "only this
  source"), and search headlines and summaries. `"Quoted phrases"` match exactly. Press `/`
  to jump to the search box.
- **Watchlist.** Add terms you track (your organisation, threat actors, CVE IDs, countries)
  and matching items are highlighted and collected under *Watchlist hits*.
- **New since last visit.** Items that arrived since you last looked get a **NEW** badge.
  While the page is open it checks for fresh items every 5 minutes.
- **Read and saved.** Opening an item marks it read. Star items to keep them under *Saved*,
  even after they drop out of the 7-day window.
- **Source health.** A green or orange dot next to each source shows whether its last
  refresh worked. A warning appears if the whole feed stops updating.
- Light and dark mode, and a phone-friendly layout.

Your watchlist, read and saved items live only in your browser. Nothing about them is
sent anywhere or stored in this repository. Use **Back up settings** and **Restore** at the
bottom of the sidebar to move them to another device or browser.

Browsers keep that data per site origin, and every GitHub Pages project of one account shares
the origin `<account>.github.io`. Other project sites you publish there can therefore read it
(your watchlist terms, for example). Publish only sites you trust under the same account, or give
Owlfeed its own origin with a custom domain.

## How it works

```
sources.yml ─► GitHub Action (every 15 min) ─► data/feed.json ─► GitHub Pages ─► your browser
                       ▲                                                │
                       └──────── previous feed.json from the live site ─┘
```

1. A scheduled GitHub Action ([`refresh.yml`](.github/workflows/refresh.yml)) refreshes the
   feed about every 15 minutes. (It wakes every 5 minutes and skips while the live feed is
   under 12 minutes old, because GitHub often starts scheduled runs late or drops them.) It
   downloads every feed in [`sources.yml`](sources.yml) and tidies titles,
   links and summaries. Then it merges them with the feed that is already live and drops
   anything older than 7 days.
2. It publishes the result, a static page plus `data/feed.json`, to GitHub Pages. Just before
   uploading, `python -m owlfeed stamp site` adds a content hash (`?v=…`) to every CSS and
   JavaScript URL, so a reader arriving mid-deploy never mixes cached old files with new ones.
3. The page in your browser reads `data/feed.json`. No server, database or API key is
   involved, and it costs nothing on a public repository.

Feeds are fetched politely: a descriptive user agent, conditional requests (only download
when something changed), timeouts, and one retry. Each download is capped at 10 MB and
60 seconds, and the whole fetch at 3 minutes, so one misbehaving site can't hold up the
rest. If one source fails, its earlier items stay on the dashboard and its dot turns orange.
If every source fails at once, nothing is published and the current dashboard stays up.

Each refresh also saves a copy of the feed with its run, and the next refresh picks it up from
the last successful one. That copy is only used if the live `feed.json` ever answers "not
found", so a GitHub Pages hiccup can't wipe the 7-day history.

## One-time setup

GitHub Pages is free for public repositories, so:

1. **Make the repository public:** *Settings → General → Danger Zone → Change visibility →
   Public*.
2. **Turn on Pages:** *Settings → Pages → Build and deployment → Source:* **GitHub Actions**.
3. **Merge this work into `main`.** The push to `main` starts the first refresh. After about a
   minute the dashboard is live at https://scyyan.github.io/Owlfeed/.

To refresh by hand at any time: *Actions → Refresh feed → Run workflow*.

## Sources

| Category | Group | Sources |
|---|---|---|
| Cyber | Government & CERT | CISA advisories, UK NCSC, SANS Internet Storm Center |
| Cyber | Threat research | Google Threat Intelligence (Mandiant), Microsoft Threat Intelligence, Cisco Talos, Unit 42, Kaspersky Securelist, ESET WeLiveSecurity, Check Point Research, SentinelLabs, Sophos X-Ops, The DFIR Report |
| Cyber | Security news | The Record, BleepingComputer, Krebs on Security, The Hacker News, SecurityWeek, Dark Reading, CyberScoop, Risky Bulletin |
| Geopolitics | Analysis & investigations | Bellingcat, International Crisis Group, DFRLab, Atlantic Council, The Interpreter (Lowy Institute), FDD's Long War Journal, RUSI |
| Geopolitics | World news | BBC News – World, Al Jazeera, The Guardian – World |

Ready to switch on (they're in `sources.yml` with `enabled: false`): Help Net Security,
Infosecurity Magazine, Ars Technica – Security, Foreign Policy, War on the Rocks,
Just Security, The Diplomat, The Kyiv Independent, DW, France 24 and UN News.

Some sources were considered but left out because they don't offer a usable feed:

- **Institute for the Study of War (ISW):** blocks automated requests from GitHub's servers.
  Its Ukraine and Iran assessments are covered indirectly by the outlets above.
- **Critical Threats (AEI)** and **ACLED** publish no RSS feed.
- **CSIS:** its only feed stopped updating in 2016.

### Adding, removing or pausing a source

Edit [`sources.yml`](sources.yml); GitHub's web editor (the pencil icon) works fine. Each
source looks like this:

```yaml
  - id: bellingcat                       # unique, lowercase, dashes allowed
    name: Bellingcat                     # shown on every item
    feed: https://www.bellingcat.com/feed/
    site: https://www.bellingcat.com/
    category: Geopolitics                # one of settings.categories at the top of the file
    group: Analysis & investigations     # one of that category's groups
```

Optional settings:

- `enabled: false` keeps a source listed but doesn't fetch it.
- `exclude_title: ["^Sponsored"]` skips headlines matching a regular expression.
- `summary_from: content` summarizes the article body instead of the feed's teaser.
- `timezone: Europe/Brussels` is for feeds whose dates carry no time zone.

Feed URLs must use `https://`. To add a category or group (say, *Defense*), list it under
`settings.categories` at the top of `sources.yml` first.

Every push runs the **CI** workflow. Its *Feed check* job downloads every feed from GitHub's
network and posts a table of what works in the run's summary. Check it after adding a
source. If `sources.yml` has a mistake (a missing field, a duplicate id, a category that isn't
listed, an `http://` feed, broken YAML), the refresh stops before publishing and the dashboard
keeps its last data. The CI run for that push shows exactly what's wrong.

## Troubleshooting

- **"Updated 3 hours ago" in orange.** The scheduled refresh isn't running. Open the
  *Actions* tab and check *Refresh feed*. GitHub pauses schedules in public repositories
  after 60 days without activity. The *Keepalive* workflow re-enables them weekly to
  prevent that. If the refresh still shows as disabled, click **Enable workflow**.
- **"Updated 40 minutes ago" now and then.** GitHub starts scheduled runs late, or skips them,
  when it is busy. Runs that skipped because the feed was fresh show their *Fetch feeds* job
  as skipped; that is normal. To refresh at once, run *Refresh feed* by hand
  (*Actions → Refresh feed → Run workflow*).
- **A source has an orange dot.** Hover over it to see the error. Sites sometimes move their
  feeds or block automated requests. Find the new feed URL, update `sources.yml`, and
  confirm it in the CI *Feed check* summary.
- **GitHub's "There isn't a GitHub Pages site here" page.** The first refresh hasn't finished
  or it failed. Check that *Settings → Pages → Source* is **GitHub Actions**, then open the
  *Refresh feed* run in the *Actions* tab.
- **"No feed data published yet"** when you open `site/index.html` yourself. The page needs
  `site/data/feed.json`; run `python -m owlfeed build` first (see Development).

## Development

```sh
python -m venv .venv && . .venv/bin/activate
pip install --require-hashes -r requirements.txt -r requirements-dev.txt   # pinned with hashes

python -m owlfeed build                 # fetch every feed into site/data/feed.json
python -m owlfeed check --samples 3     # health report for every source
python -m http.server -d site 8000      # then open http://localhost:8000
python -m owlfeed stamp path/to/copy    # version asset URLs in a site copy (CI does this; not your working tree)

python -m pytest --ignore=tests/e2e     # fetcher unit tests
npm test                                # dashboard unit tests (Node 22+, no dependencies)
python -m playwright install chromium
python -m pytest tests/e2e              # browser tests against a fixed sample feed
```

Layout:

- `owlfeed/`: the Python fetcher (`config`, `fetch`, `parse`, `text`, `store`, CLI in `__main__`).
- `site/`: the dashboard (plain HTML, CSS and ES modules; no build step).
- `tests/`: pytest suites, sample feeds, Node unit tests and Playwright browser tests.
- `.github/workflows/`: CI, the 15-minute refresh and deploy, and the keepalive.
- `requirements.in` and `requirements-dev.in`: direct dependencies. The `.txt` files are
  generated from them with `pip-compile --generate-hashes --strip-extras <file>.in`
  (from `pip-tools`).
