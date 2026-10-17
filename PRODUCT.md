# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

The owner and a small team who follow the same feed. Everyone reads the same public
dashboard, and each person keeps their own watchlist, read and saved items in their own browser.

They use it in four ways, all of which matter:

- **Daily briefing scan:** a focused 5–15 minute catch-up on what changed since the last visit.
- **All-day monitoring:** left open on a second screen and glanced at when new items arrive.
- **On the phone:** quick checks between tasks.
- **Topic research:** searching and filtering for a specific threat actor, CVE, organisation or
  country.

## Product Purpose

Owlfeed is an OSINT news dashboard for cyber threat intelligence and geopolitics and conflict,
in the spirit of Feedly or Recorded Future. It gathers the latest reporting from hand-picked
sources into one timeline, newest first. Each item shows its headline and a short summary, and
the headline opens the original article in a new tab. Success means a reader can tell what
changed, what matters to them (watchlist hits) and where to read more, without visiting 31 sites.

## Positioning

A free, self-hosted alternative to paid intelligence feeds. There's no account and no tracking,
and the team controls the source list. The sources are a deliberately curated set of government
CERTs, threat-research labs, security news, conflict analysis and world news (see `sources.yml`).
Everything a reader does stays in their own browser.

## Operating Context

- A GitHub Action fetches every source every 15 minutes, merges the results with the live
  feed, keeps 7 days and publishes to GitHub Pages. If a refresh fails, the last good data
  stays up.
- Readers are often switching between the dashboard and source articles in other tabs.
- Freshness is part of the job: readers need to see when data was updated, whether each source
  is healthy, and which items are new since their last visit.

## Capabilities and Constraints

- **Fixed (confirmed): free, no server.** The product is a static site on GitHub Pages plus
  GitHub Actions, with no backend, database, paid service or API key.
- **Fixed (confirmed): private by default.** Watchlist, read state, saved items and preferences
  live only in the reader's browser (localStorage). Moving them happens through manual backup
  and restore.
- Current features: category, source and text filters (quoted phrases match exactly; `/` focuses
  search), watchlist highlights with a *Watchlist hits* view, "new since last visit" badges,
  5-minute auto-refresh with a new-items pill, read/unread, starred saved items that outlive the
  7-day window, per-source health dots, a stale-data warning, light/dark mode following the
  system with a toggle, and a phone drawer layout.
- The dashboard is plain HTML, CSS and ES modules with no build step. A strict CSP allows only
  `'self'` (no inline scripts or styles from elsewhere, no eval). Feed text is always rendered as
  text, and only http(s) links are rendered.
- Categories and groups are declared in `sources.yml`. Currently that's Cyber (Government & CERT,
  Threat research, Security news) and Geopolitics (Analysis & investigations, World news).
- **Open, not commitments:**
  - Summaries currently come from each source's own feed text, with no AI. That is how it works
    today, not a rule.
  - Sources are hand-picked today, but the user didn't make "trusted sources only" a rule.
  - There's no shared team state (such as a shared watchlist or shared saved items). Adding it
    would have to fit "free, no server".

## Brand Commitments

The name is Owlfeed, and the favicon is at `site/favicon.svg`. No other brand commitments have
been made.

## Evidence on Hand

- A live feed built locally from 31/31 healthy sources (`site/data/feed.json`, about 330 items
  across 7 days).
- A fixed sample feed for tests and screenshots: `tests/e2e/sample_data.py` (NOW =
  2026-10-15T14:00Z).
- There are no user metrics, testimonials or outside users to cite. Don't invent any.

## Product Principles

1. **Freshness you can trust.** Always show how current the data is and which sources are
   failing. Never show stale data as if it were live.
2. **Scan first, then go deeper.** The timeline should work for a fast briefing scan and a
   glance from a second screen. Depth (filters, search, watchlist) is there when needed but never
   gets in the way of the scan.
3. **The source is the authority.** Owlfeed points to the original reporting and says which
   outlet it came from. It never rewrites or claims the content as its own.
4. **Private and free by construction.** No feature may require a server, an account or sending
   a reader's activity anywhere.
5. **Works wherever you check.** Phone, laptop and second screen are all first-class.

## Accessibility & Inclusion

Keep the existing bar: WCAG AA colour contrast in both themes, full keyboard operation, focus
kept across live re-renders, screen-reader announcements for new items and actions, and an inert
modal drawer on phones. The browser tests in `tests/e2e/` cover these behaviours.
