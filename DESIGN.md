---
name: Owlfeed
description: A watchful OSINT timeline for cyber threat intelligence and geopolitics.
colors:
  night-sky-blue: "#2453c8"
  night-sky-blue-soft: "#e7edfb"
  night-sky-blue-dark: "#7aa5ff"
  night-sky-blue-soft-dark: "#1b2650"
  cyber-blue: "#2563eb"
  cyber-blue-dark: "#7aa5ff"
  geopolitics-teal: "#0a7380"
  geopolitics-teal-dark: "#3cc6d0"
  other-violet: "#7c3aed"
  other-violet-dark: "#b794f6"
  owls-eye-amber: "#a15c00"
  owls-eye-amber-soft: "#fdf0d9"
  owls-eye-amber-dark: "#f5c451"
  owls-eye-amber-soft-dark: "#3a2c10"
  owls-eye-wash: "#fef6e8"
  owls-eye-wash-dark: "#27221c"
  saved-amber: "#b45309"
  highlight-gold: "#ffe58f"
  fresh-green: "#0f6e33"
  fresh-green-soft: "#dff4e6"
  fresh-green-dark: "#4ade80"
  fresh-green-soft-dark: "#10301f"
  healthy-green: "#16a34a"
  alarm-rust: "#b93d06"
  alarm-rust-dark: "#fb8b4b"
  dawn-canvas: "#f4f5f7"
  paper: "#ffffff"
  paper-raised: "#eef0f3"
  ink: "#15181d"
  ink-soft: "#3f4753"
  slate-muted: "#5f6874"
  hairline: "#e1e4e9"
  midnight-canvas: "#0a0e1a"
  midnight-surface: "#10162a"
  midnight-raised: "#182039"
  moonlit-ink: "#e7ebf5"
  moonlit-ink-soft: "#b9c2d9"
  moonlit-muted: "#8b95b1"
  midnight-hairline: "#252e4a"
  owl-indigo: "#1e3a8a"
  scrim: "rgb(0 0 0 / 40%)"
typography:
  headline:
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif"
    fontSize: "18px"
    fontWeight: 700
    letterSpacing: "0.2px"
  title:
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif"
    fontSize: "17.5px"
    fontWeight: 650
    lineHeight: 1.35
  body:
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.5
  summary:
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.5
  meta:
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif"
    fontSize: "12.5px"
    fontWeight: 400
    fontFeature: "tnum"
  label-day:
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif"
    fontSize: "13px"
    fontWeight: 700
    letterSpacing: "0.4px"
  label-section:
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif"
    fontSize: "11.5px"
    fontWeight: 650
    letterSpacing: "0.7px"
rounded:
  mark: "3px"
  xs: "6px"
  sm: "8px"
  md: "10px"
  lg: "12px"
  pill: "999px"
spacing:
  xxs: "4px"
  xs: "6px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
components:
  button:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "6px 12px"
  button-hover:
    backgroundColor: "{colors.paper-raised}"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.ink-soft}"
    rounded: "{rounded.sm}"
    padding: "6px 12px"
  icon-button:
    backgroundColor: "transparent"
    textColor: "{colors.ink-soft}"
    rounded: "{rounded.sm}"
    size: "36px"
  item-action:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink-soft}"
    rounded: "{rounded.sm}"
    size: "34px"
  item-action-saved:
    backgroundColor: "{colors.owls-eye-amber-soft}"
    textColor: "{colors.saved-amber}"
  item-action-read:
    backgroundColor: "transparent"
    textColor: "{colors.slate-muted}"
  watch-status:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink-soft}"
    rounded: "{rounded.md}"
    height: "38px"
    padding: "0 12px 0 10px"
  search-input:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "8px 12px 8px 36px"
  view-nav-item:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "7px 8px"
  view-nav-item-active:
    backgroundColor: "{colors.night-sky-blue-soft}"
    textColor: "{colors.night-sky-blue}"
  watch-chip:
    backgroundColor: "{colors.owls-eye-amber-soft}"
    textColor: "{colors.owls-eye-amber}"
    rounded: "{rounded.pill}"
    padding: "2px 4px 2px 9px"
  badge-new:
    backgroundColor: "{colors.fresh-green-soft}"
    textColor: "{colors.fresh-green}"
    rounded: "{rounded.pill}"
    padding: "0 7px"
    height: "18px"
  day-group:
    backgroundColor: "{colors.paper}"
    rounded: "{rounded.lg}"
  feed-item:
    padding: "14px 16px 14px 18px"
  feed-item-watch:
    backgroundColor: "{colors.owls-eye-wash}"
  new-items-pill:
    backgroundColor: "{colors.night-sky-blue}"
    textColor: "{colors.paper}"
    rounded: "{rounded.pill}"
    padding: "7px 16px"
  toast:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.dawn-canvas}"
    rounded: "{rounded.md}"
    padding: "9px 16px"
---

# Design System: Owlfeed

## Overview

**Creative North Star: "The Night Watch"**

Owlfeed keeps watch so its reader doesn't have to. Its interface behaves like a good sentry:
alert, unhurried and exact. The timeline is a quiet surface of headlines, sources and times, and
the screen only raises its voice for what the reader has asked to be told: something new, a
watchlist term, or a source that has gone silent. It has to be comfortable at 7 a.m. on a phone
and at midnight on a second monitor. That's why light and dark are equal citizens, and dark is
its own indigo midnight (drawn from the Owl Indigo of the brand mark), not an inversion of day.

The owl is literal in one place: the **watch status** at the head of the top bar. Its two eyes
are open with Healthy Green pupils while the feed is fresh, widen with ink-dark pupils and a
"Late" flag when a refresh runs late (the owl grows more alert, never sleepier), and close in
Alarm Rust when the data is stale. They blink once when a new build lands.

The mood is **precise**. Times line up in tabular figures, day headers stick in place, and every
item follows the same rhythm: headline, then source and time, then summary. Density is set for
scanning. A briefing reader should cover a day's reporting in minutes, and a monitoring reader
should spot a change at a glance. Expression lives in small, exact details (category dots,
health dots, a full-row watchlist wash) rather than in decoration.

**Key Characteristics:**
- A system font stack, so it renders natively, loads instantly and stays sharp everywhere.
- Neutral, layered surfaces. Color is reserved for meaning: category, freshness, watchlist,
  health and saved.
- Flat, tonal depth with hairline borders. Shadows appear only on things that float.
- A two-column workbench (sidebar plus timeline) that becomes a drawer on phones.
- The watch status anchors the top bar at every width: freshness and source health come first,
  search second.
- Every color decision is made twice, once for daylight and once for midnight, at WCAG AA.

## Colors

A cool slate-and-paper neutral base with one blue for action and a few signal hues that each
mean exactly one thing.

### Primary
- **Night Sky Blue** (#2453c8 light; #7aa5ff dark): action and current state. It marks the
  selected sidebar view and phone tab (on its soft tint, #e7edfb / #1a2640), title hover, link
  buttons, checkbox accents, focus rings, the "↑ N new items" pill, and the 6px unread dot beside
  an unread headline (still to do is a current state).

### Secondary
- **Owl's-Eye Amber** (#a15c00 light; #f5c451 dark): what the owl has noticed. It's used for
  watchlist chips and the eye-marked watchlist badge, with its soft tint behind chips and badges.
  An item that hits the watchlist takes the **Owl's-Eye Wash** (#fef6e8 / #27221c) across the
  whole row, except inside the Watchlist hits view, where every row is a hit and the eye badge
  carries the signal alone. **Saved Amber** (#b45309 light; the same #f5c451 in dark) fills the star on saved
  items. **Highlight Gold** (#ffe58f light; amber at 32% in dark) is the `<mark>` behind
  watchlist terms only; search matches use Night Sky Blue (see Components).

### Tertiary
- **Fresh Green** (#0f6e33 light; #4ade80 dark), on its soft tint (#dff4e6 / #12311f): new since
  last visit. It's used for the NEW badge. **Healthy Green** (#16a34a)
  marks a source that refreshed successfully. Read is not a signal: it is the quiet state
  (Slate Muted), so green never fills the timeline's most common row.
- **Alarm Rust** (#b93d06 light; #fb8b4b dark): something is wrong. It's used for failing-source
  dots and labels, the "updated N hours ago" warning, and the stale-data banner.

### Category hues
- **Cyber Blue** (#2563eb light; #7aa5ff dark): the dot for Cyber sources, and the ink of
  Cyber source names in item rows.
- **Geopolitics Teal** (#0a7380 light; #3cc6d0 dark): the dot and the byline ink for
  Geopolitics sources. It replaced an ember orange that sat too close to Alarm Rust and Owl's-Eye
  Amber: no category may borrow a warm hue, because warm hues mean watchlist, saved or failure.
- **Other Violet** (#7c3aed light; #b794f6 dark): the fallback dot for any future category.

### Neutral
- **Dawn Canvas** (#f4f5f7) and **Midnight Canvas** (#0a0e1a): the page behind everything, and the
  sticky day headers.
- **Paper** (#ffffff) and **Midnight Surface** (#10162a): the sidebar, day groups, buttons and
  inputs.
- **Paper Raised** (#eef0f3) and **Midnight Raised** (#182039): hover fills.
- **Ink** (#15181d) / **Moonlit Ink** (#e7ebf5): headlines and body text.
- **Ink Soft** (#3f4753) / **Moonlit Ink Soft** (#b9c2d9): summaries, and the resting color of
  icons.
- **Slate Muted** (#5f6874) / **Moonlit Muted** (#8b95b1): counts, times, section labels, and
  read items.
- **Hairline** (#e1e4e9) / **Midnight Hairline** (#252e4a): every border and divider.
- **Hover tint** (`--hover-tint`: black 8% light, white 10% dark): the press-down fill on small
  round controls such as the chip ×.
- **Scrim** (black at 40%): behind the phone drawer and the shortcuts dialog.
- **Owl Indigo** (#1e3a8a): used only in the favicon and brand mark.

### Named Rules
**The One Meaning Rule.** Each signal hue means one thing everywhere, and categories keep to
cool hues (blue, teal, violet) so they can never be mistaken for a signal. Green is new or healthy,
amber is watchlist or saved, rust is failure, blue is action, search, unread or Cyber. Never use one decoratively,
and never give a second meaning to a hue that already has one.

**The Twin Watch Rule.** Every color token ships in a light and a dark value, and both pass WCAG
AA against their own surfaces. Dark mode is indigo midnight with its own values, not inverted
light-mode ones.

## Typography

**Display Font:** none. Owlfeed has no display tier.
**Body Font:** system-ui (with -apple-system, Segoe UI, Roboto, Helvetica Neue, Arial,
sans-serif)

**Character:** The platform's own sans, used at a narrow range of sizes, with weight doing most
of the hierarchy work (400, 550, 600, 650, 700). It reads as native, quick and exact, never
editorial.

### Hierarchy
- **Headline** (700, 18px): the Owlfeed wordmark only. Dialog and empty-state titles use Title.
- **Title** (650, 17.5px, 1.35; 17px under 600px; 15.5px in compact rows): item headlines, 1.25×
  the summary so the headline leads by size as well as weight. A headline that has been read
  or visited drops to 550 and Slate Muted.
- **Body** (400, 15px, 1.5): the base for UI text, empty states and sidebar rows (13.5px).
- **Summary** (400, 14px, 1.5, Ink Soft): the source's summary under each headline, clamped to
  two lines (three on phones) and shown in full on the row under the keyboard cursor.
- **Meta** (400–600, 12.5px, tabular numbers): source, time, relative age and badges. Counts are
  12px with tabular numbers.
- **Day label** (700, 13px, 0.4px tracking, uppercase): "TODAY", "YESTERDAY", followed by the
  date in 500 sentence case.
- **Section label** (650, 11.5px, 0.7px tracking, uppercase, Slate Muted): the sidebar headings
  CATEGORIES, WATCHLIST and SOURCES.

### Named Rules
**The Tabular Time Rule.** Every number that can change (counts, times, ages) uses tabular
figures, so the columns hold still while the feed updates.

**The Weight-Not-Size Rule.** Express hierarchy with weight and color before adding a new font
size. The scale stays within 11.5–18px.

## Layout

A two-column workbench. On wide screens it has a sticky 292px sidebar with its own scrolling,
and a main column with a sticky 60px top bar: watch status first, then search, then
"Mark N read" and the theme toggle. Sources in the sidebar fold into collapsible groups
(category › group, with a shown/total tally); a group with a hidden or failing source stays open. Below
the top bar is the timeline, capped at 880px wide and centered, with 24px side padding and 96px
of space at the bottom.

The timeline is grouped by day. Each day has a sticky header that pins just under the top bar,
over one bordered group of items. An item is a two-column grid: content on the left, and a
narrow column of actions (save, read) on the right that spans the title and meta rows.

The spacing scale is a 4px grid used tightly: 4, 6, 8, 12, 16 and 24px, plus 14px for item
padding. Sidebar rows are compact (4–8px vertical padding), and items breathe more (14px).

**Responsive:**
- **≤1100px:** the watch status takes its compact form (as on phones), "Mark N read" shortens to
  "Mark N", and the top bar tightens to 16px padding and 8px gaps. **≤1000px:** "Mark N" becomes a
  38px icon. Only the search shrinks (never below 220px, 200px under 1000px).
- **≤900px:** the sidebar becomes an off-canvas drawer, min(88vw, 330px) wide. It slides in over
  a 40% black scrim and is inert and modal while open. A menu button appears in the top bar, and
  the content padding drops to 16px.
- **≤600px:** the watch status shows its compact form ("9m", plus the source tally only while a
  source is failing), the theme toggle moves into the drawer as a text link, inputs are 16px (so
  iOS never zooms on focus), "Mark N read" moves into
  the drawer, the search placeholder shortens to "Search", item padding tightens to 12px/10px,
  titles drop to 17px, and summaries clamp to three lines. Headlines and summaries run the full
  row width; save and read sit side by side at the end of the meta line. Rows start comfortable,
  as on wider screens, until the reader picks a density. A **tab bar** fixed to the bottom (All, New, Hits, Saved with
  their counts, plus Filters, which opens the drawer) replaces the top-left menu button, keeps
  the main views within thumb reach, and names the current view, so the idle bar is hidden.
- **Drawer footer on touch:** settings links become a two-column grid of 44px bordered targets,
  and "Shortcuts" is hidden (it only helps with a keyboard).
- **Touch (`hover: none`):** controls that only appear on hover, such as the source "only"
  shortcut, are always visible, and item actions, icon buttons, the watch status and the search
  field are at least 44px.

## Elevation & Depth

Flat and tonal. Depth comes from three layers of surface (canvas, then paper, then raised) and
1px hairline borders, not from shadows. A day group sits on the canvas with a hairline border and,
in light mode only, a faint 1px ambient shadow. In dark mode that shadow is removed entirely.
Real shadows are kept for elements that float above the timeline.

### Shadow Vocabulary
- **Resting hint** (`box-shadow: 0 1px 2px rgb(16 24 40 / 5%)`): day groups in light mode only.
- **Floating** (`box-shadow: 0 6px 18px rgb(0 0 0 / 18%)`): the new-items pill, the status
  toast, the watch report panel and the shortcuts dialog.
- **Drawer** (`box-shadow: 0 0 40px rgb(0 0 0 / 25%)`): the phone sidebar while open.
- **Glass bar:** the top bar is 90% canvas with `backdrop-filter: blur(10px)` and a hairline
  bottom border. It is the one translucent surface.

### Named Rules
**The Only-What-Floats Rule.** Surfaces are flat at rest. A shadow means the element is
temporarily above the timeline (pill, toast, drawer). Never give a static card a lift shadow.

## Shapes

Softly rounded rectangles, sized by role:
- 12px for containers (day groups, empty state)
- 10px for fields and banners (search, active filters, stale banner, toast)
- 8px for controls (buttons, icon buttons, sidebar rows, watch input)
- 6px for small rows and the "only" button
- 3px for highlighted text

Fully round (999px) shapes mean status or tags: badges, watch chips and the
new-items pill. Dots (8px source and health dots, 7px item category dots) are circles. Icons are
18px line icons with a 2px stroke and round caps and joins, drawn inline as SVG. The brand mark
is an owl on a 14/64-rounded indigo tile.

**The Round-Means-Signal Rule.** A fully rounded pill is always a status or a tag. Never use pill
shapes for ordinary command buttons.

## Components

Component philosophy: **tactile and firm.** Controls should look like things you can press.
That means visible surfaces, clear hover and pressed states, and confident active states, while
headlines still lead.
Item actions, the top-bar buttons and the watch status all carry a Paper surface and a hairline
border at rest. Ghost buttons remain only where a control sits inside running text or a list.

### Buttons
- **Shape:** gently rounded (8px).
- **Default:** Paper surface, hairline border, 13.5px text, 6px × 12px padding (small: 5px × 10px,
  13px). Hover fills with Paper Raised. Disabled drops to 55% opacity. Bulk actions name their
  scope in the label ("Mark 12 read") and offer Undo in the toast.
- **Ghost:** transparent border and fill, Ink Soft text. Hover fills with Paper Raised and darkens
  the text to Ink.
- **Icon button:** a 36px square, transparent, Ink Soft. Hover is the same as Ghost.
- **Link button:** Night Sky Blue text at 13px with no chrome, underlined on hover. Used for
  secondary sidebar actions (Back up settings, Restore).
- **Focus:** every control gets a 2px Night Sky Blue outline with a 2px offset (`:focus-visible`).

### Chips
- **Watch chip:** (counts and upgrades: see Watchlist upgrades below) a pill in Owl's-Eye Amber on its soft tint, 12.5px at 600 weight, with a 20px
  circular × button for removal. Re-adding a listed term keeps the typed text and pulses the
  existing chip with a 3px Owl's-Eye Amber ring (an outline under reduced motion).
- **Badges:** 18px-tall pills at 11.5px and 700 weight. NEW is uppercase Fresh Green, and the
  watchlist badge is Owl's-Eye Amber.

### Cards / Containers
- **Day group:** a 12px radius, a Paper surface, a hairline border and the resting-hint shadow
  (light only). It clips its items, which are separated by hairline borders.
- **Feed item:** 14px × 16px padding with 18px on the left. A watchlist hit takes the Owl's-Eye
  Wash across the whole row.
- **Empty state:** a 12px radius with a dashed hairline border, centered, 36px × 24px padding.
  An empty state is never a dead end: it names what was searched or when "since" was, and offers
  the one next step (Clear filters, Go to Unread, or the * version of a search that would match).
  It never claims an all-clear it can't know: while the feed is stale, "New since" reads "No
  refresh since 9:58 PM", and a disabled bulk button reads "Nothing to mark", not "All read".

### Inputs / Fields
- **Search:** a Paper surface, hairline border, 10px radius, and an 18px magnifier icon inset
  11px from the left. It's the widest control in the top bar (up to 520px). Pressing `/` focuses
  it.
- **Watch input:** a Canvas fill (sunken compared with the Paper sidebar), hairline border, 8px
  radius, and an "Add" button beside it.
- **Checkboxes:** native checkboxes tinted with Night Sky Blue.
- **Focus:** the shared 2px Night Sky Blue outline.

### Navigation
- **Sidebar views** (All items, New since last visit, Unread, Saved, Watchlist hits): full-width
  rows, 8px radius, with the count right-aligned in tabular numbers. Hover fills with Paper Raised.
  The current view uses Night Sky Blue text at 600 weight on its soft tint.
- **Category and source filters:** checkbox rows with a category dot or health dot, labels cut
  off with an ellipsis, and a per-source "only" shortcut. A failing source's label turns Alarm
  Rust. A category checkbox always agrees with its sources: checked when all are shown, mixed
  (indeterminate) when some are, empty when none are, and its count is what it shows now.
  Checking a category shows all of its sources again.
- **Phone:** the drawer pattern described under Layout.

### Timeline Item (signature)
The unit everything else serves. A headline (Title) links to the source in a new tab. Under it
is a meta row: the source name at 650 weight in its category ink with its dot, the local time,
the relative age, and badges (the watchlist badge carries a drawn eye). Then comes the summary.
Save (star) and read (ring) buttons are stacked on the right as firm 34px squares. The keyboard
cursor (Tab or j/k) tints the whole row with Night Sky Blue's soft tint, not just the headline. Saved fills
the star in Saved Amber on the amber tint. Unread rows carry the mark: a 6px Night Sky Blue dot
in the gutter, centred on the headline's first line (none in the Unread view, where every row is
unread). Read is the quiet state: the ring fills with a Slate Muted check, with no tint, and the
headline and summary fade to Slate Muted. Undated
items show a `~` before their time. Search matches are underlined in Night Sky Blue on its soft
tint; watchlist terms keep Highlight Gold. Where both cover the same word, the watchlist mark wins
and the search underline is dropped: two highlight styles never stack. Search and the watchlist
share one matching rule (whole words; a trailing * matches longer words), so what is highlighted
is exactly what matched.

**Density.** Comfortable (headline, meta, two-line summary) is the default. Compact (toggle in the
top bar, "Compact rows" in the phone drawer, or `d`) shows headline and meta only, 7px row padding
and the actions side by side at 30px (44px on touch); the focused row reveals its summary. The
choice is saved with the reader's preferences.

**Quiet actions.** With a mouse, the read button and an unused save button rest as bare Slate
Muted icons and firm up (Paper, hairline) when the row is hovered or focused. Only saved always
shows its tint. Touch keeps the firm 44px buttons.

**Watchlist chips are filters.** The chip body is a toggle with a tabular hit count: pressed, the
Watchlist hits view shows that term alone (2px Owl's-Eye Amber outline, filled count). A term with
no hits keeps a muted count. A read hit keeps half the Owl's-Eye Wash.

**Filter tokens.** The active-filters bar shows the item count and one token per constraint (view,
term, categories, sources, search): a 6px-radius Paper control with an ×, removable on its own.
"Clear all" appears once there are two or more. A search-only empty state offers "Clear search";
when one filter hides every match, the empty state names it ("4 matches are hidden by the category
filter") and offers to lift just that one.

**Counts follow the search.** View, category, source and watchlist-chip counts all count matches
for the current search, so the sidebar and timeline never disagree. While a search is active the
sidebar counts turn Night Sky Blue at 650 weight.

**Briefing views (New, Unread).** A one-line summary leads ("129 new · 12 watchlist hits · Cyber
80 · Geopolitics 49", tabular, Ink Soft with Ink numbers). The newest five watchlist hits come first in
their own section, headed "WATCHLIST HITS · Newest 5 of 38" in Owl's-Eye Amber (the rows drop the
wash there, as in the hits view), with "Show all 38 hits here" below them; the other hits stay in
the timeline in time order. The list ends with a hairline and a finish line. With unread items
left it reads "End of the list · 327 unread items" and offers "Mark these 327 read" (Undo in the
toast); only with nothing unread does it say "You're caught up to 9:58 PM". While stale it says
why. The summary and finish line update in place as items are read. NEW badges are hidden in the
New view, where every row is new. All items, Saved and Watchlist hits keep strict time order.

**Summary counts are filters.** The briefing summary is a list (screen readers hear each part),
with "·" separators drawn in CSS. "31 watchlist hits" opens all the briefing's hits in the pinned
section and moves there, so the number clicked is the number shown; a category count ("158 Cyber")
shows that category alone within the briefing. The view's own count is plain. Nothing in the
summary leaves the briefing.

**Watchlist upgrades.** When a whole-word term's prefix form would catch more ("Zelensky" misses
"Zelenskyy"), one quiet Slate Muted line under the chips says so: "1 term could catch more.
Review". Review lists each offer as a dashed amber button, "Zelensky → Zelensky* +3"; one tap
replaces the term in place and keeps focus on the new chip. Chip counts follow the current view
(in New, a chip counts that briefing's hits), and sit on Paper so amber numbers keep 4.5:1.

**Why a row is here.** When a search (or, in Watchlist hits, a watch term) matches only past the
two visible summary lines, the summary starts a few words before the match with "…", so the
highlight is always on screen.

**Density and Mark read icons.** The density toggle draws two rules with arrows closing between
them (never three or four bars, which read as the menu). At 1000px and below, "Mark N read" keeps
its count beside the double check ("✓✓ 328"). On phones in compact mode only the star shows: rows
stay one tap target tall, opening an item marks it read, and "Mark these N read" closes out a list.

**Saved is an archive.** When category or source filters hide some saved items, the filter bar
says how many ("2 saved items hidden by your filters") with "Show them".

**Starting up.** A plain script (`js/boot-check.js`) outside the module graph watches the start:
if one of the site's scripts fails or the app hasn't started within 10 seconds, "Loading…"
becomes "Owlfeed couldn't start" with a Reload button, announced to screen readers. Without
JavaScript a `<noscript>` empty state says so. While the feed loads, the sidebar's category and
source lists show muted placeholder bars.

**Glossary.** "What the labels mean" defines New, Unread (the dot), Just arrived, Read (the ring and check), Saved
(the star) and a watchlist hit (the amber row and eye badge), each drawn with its real glyph.

**Help on touch screens.** The drawer's "What the labels mean" opens the help dialog, which on
touch drops the keyboard shortcuts and leads with the label glossary and search rules.

**Briefing chrome.** New and Unread carry no view token and no idle bar: the summary line names
them. While stale, the banner gives way in these views to the summary's first item, "Stale: last
update 9:58 PM, 1 day ago" in Alarm Rust. The summary's
"·" separators end their item, so a wrapped line never starts with one.

**One name for new.** NEW is always "since your last visit" (with its time), or on a first visit
"in the 24 hours before the last update", measured from the build, so stale rows can still say
"2d ago". The summary line, empty state and help glossary use exactly these words.

**Searches widen once.** When a whole-word search finds nothing here and its prefix form does,
the prefix form runs: the search token reads "Search: ransom*" and a line explains "No whole-word
matches for “ransom”, so showing ransom*" with "Search exactly" to go back to strict.

**Watchlist edits speak and undo.** Adding a term announces its hit count; removing one shows a
toast with Undo (and Ctrl/⌘ Z), which puts the term back in its old place.

**Measure.** Summaries cap at 60ch (about 80 characters). Placeholders use Slate Muted, not the browser's grey.

**Search variants.** When the prefix form of a search finds more ("Zelensky" → "Zelensky*"), the
filter bar offers it: "+3 more as Zelensky*". In briefing views the filter bar drops its own count
(the summary line carries it). There is no "N new" chip: the New view in the sidebar carries the
count, so the top bar keeps its width for the search.

**Hidden categories** show what showing them would add, muted and in brackets ("(170)"), never a
bare 0. Day headers name the weekday once ("FRIDAY Oct 16"; Today and Yesterday keep "Sat, Oct 17").
A second skip link, "Skip to search", sits beside "Skip to timeline".

**"New" vocabulary.** NEW means arrived since the last visit; on a first visit, published in the
last 24 hours. Items landing while the page is open are "just arrived" (the pill). The help
dialog spells out New, Unread and Just arrived.

### Freshness Signals (signature)
- **Watch status:** the top bar's anchor at every width. A 38px Paper button with the owl's eyes,
  "Updated 9 min ago" and a "31/31 sources" tally after a hairline divider. Fresh (≤30 min): eyes
  open, Healthy Green pupils. Running late (30–60 min): pupils widen (1.3×) in Ink, the border
  firms to Ink Soft, the text darkens to Ink, and a pill flag reads "LATE". Stale (>60 min): eyes
  closed, rust border, text and "STALE" flag. Hollow pupils mean only "loading". Any failing source turns the tally rust. It opens a
  floating watch report (last sweep, sources answered, schedule, who isn't answering, and a short
  legend for Eyes open / Late / Stale / the tally). Vocabulary the status introduces is always
  spelled out there, never only in a tooltip.
- **Blink:** the eyes blink once (0.42s, expo ease-out) when a new build is applied. It is the
  system's one authored motion, and it is removed under reduced motion.
- **Stale banner** (one short line on phones: "Last update 1 day ago. Newer reports may be missing."): an Alarm Rust outlined box with a 10px radius above the timeline, written for
  readers ("last updated 3 hours ago (9:58 PM). Newer reporting may be missing."), with a "Hide
  for now" link that hides it for that build for the rest of the session. The chip keeps saying
  STALE. Fixes for the site owner (the Refresh feed workflow, linked on GitHub Pages) appear only
  in the watch report.
- **New-items pill:** a Night Sky Blue pill fixed under the top bar, centered on the timeline,
  with the Floating shadow.
- **Toast:** an inverted box (Ink background, Canvas text, 10px radius), fixed near the bottom,
  with the Floating shadow. An action toast (Undo) stays 10 seconds, holds while hovered or
  focused, and only its button takes pointer events.
  It never blocks taps underneath it.

## Do's and Don'ts

### Do:
- **Do** take every color from the tokens, and define it for both light and dark mode at WCAG AA.
- **Do** keep each signal hue to its single meaning: green for new or healthy, amber for
  watchlist or saved, rust for failure, blue for action or Cyber.
- **Do** use tabular figures for every count, time and age.
- **Do** build hierarchy from weight and the Ink / Ink Soft / Slate Muted steps within the
  11.5–18px scale before adding sizes.
- **Do** separate surfaces with hairline borders and canvas/paper/raised steps, and keep shadows
  for things that float.
- **Do** give every interactive element a visible `:focus-visible` outline, a 32px+ target, and
  a visible affordance on touch screens.
- **Do** give controls the tactile and firm treatment: a visible surface or border at rest, plus
  a clear hover and pressed state.
- **Do** make every bulk action name its scope and be undoable.
- **Do** make a warning state louder than the calm state it replaces. Never signal trouble by
  dimming.

### Don't:
- **Don't** add a display or web font. The system stack is the identity, and the strict CSP
  allows only `'self'`.
- **Don't** add lift shadows to static cards or day groups. In dark mode, don't add resting
  shadows at all.
- **Don't** use pill shapes for command buttons. Pills mean status or tags.
- **Don't** use signal colors (green, amber, rust) for decoration, branding or emphasis.
- **Don't** let anything compete with headlines for attention in the timeline. No imagery,
  thumbnails or decorative icons in item rows.
- **Don't** mark rows or callouts with a colored edge thicker than 1px. Use a full-row wash, as
  watchlist hits do.
- **Don't** use pure black (#000) or pure white text on the midnight canvas. Use Midnight Canvas
  and Moonlit Ink.
