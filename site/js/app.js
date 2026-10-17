// Owlfeed dashboard: loads data/feed.json and keeps the page in sync with it.

import { filterItems, fold, parseQuery, prefixSuggestion, sortItems, VIEWS } from './filters.js';
import * as ui from './render.js';
import { createStorage } from './storage.js';
import { clockTime, dayKey, parseTime, updatedLabel } from './time.js';
import { addTerm, buildMatcher, normalizeTerm, removeTerm } from './watchlist.js';

const FEED_URL = 'data/feed.json';
const POLL_MS = 5 * 60_000;
const TICK_MS = 30_000;
const STALE_MS = 60 * 60_000;
// The feed refreshes every 15 minutes; past this it is running late (but not yet stale).
const AGING_MS = 30 * 60_000;
// Away from the tab for this long (or a reload after this long) starts a new "visit".
const VISIT_GAP_MS = 30 * 60_000;
const AT_TOP_PX = 200;
const SESSION_KEY = 'owlfeed:v1:visit';

const $ = (id) => document.getElementById(id);
const plural = (count, noun) => `${count} ${count === 1 ? noun : `${noun}s`}`;
const storage = createStorage();
const narrow = window.matchMedia('(max-width: 900px)');

const state = {
  data: null,
  items: [],
  itemsById: new Map(),
  sources: [],
  sourcesById: new Map(),
  categories: [],
  prefs: storage.prefs(),
  terms: storage.watchlist(),
  matcher: null,
  query: '',
  tokens: [],
  baseline: NaN, // generated_at (server time) of the newest build seen before this visit
  seenGeneratedAt: null, // generated_at of the newest build shown while the page was visible
  hiddenAt: null,
  pending: null,
  lastFetch: 0,
  retryTimer: null,
};
if (!VIEWS.includes(state.prefs.view)) state.prefs.view = 'all';

// Source groups the reader expanded this visit (collapsed by default to keep the sidebar short).
const openGroups = new Set();

// Snapshots of items un-starred this session, so starring one again still works after it
// has dropped out of the feed.
const unsavedSnapshots = new Map();

const feedRenderer = ui.createFeedRenderer($('feed'), $('sentinel'));

// ── Visits and "new since last visit" ───────────────────────────────────────
// NEW means: first seen by the fetcher after the newest feed build this reader had on screen
// when they last left. Both sides are server timestamps, so client clocks and deploy lag
// don't matter, and items held behind the "new items" pill don't count as seen.
function readSession() {
  try {
    const value = JSON.parse(sessionStorage.getItem(SESSION_KEY));
    return value && typeof value.at === 'number' ? value : null;
  } catch {
    return null;
  }
}

function writeSession() {
  try {
    const baseline = Number.isFinite(state.baseline) ? new Date(state.baseline).toISOString() : null;
    sessionStorage.setItem(SESSION_KEY, JSON.stringify({ baseline, at: Date.now() }));
  } catch {
    // sessionStorage unavailable: a reload simply starts a new visit.
  }
}

function startVisit() {
  storage.invalidate('lastVisit');
  state.baseline = parseTime(storage.lastVisit()); // NaN on a first visit: set from the first data
  writeSession();
}

function initVisit() {
  const session = readSession();
  if (session && Date.now() - session.at < VISIT_GAP_MS) {
    state.baseline = parseTime(session.baseline); // a reload keeps this visit's NEW badges
  } else {
    startVisit();
  }
}

function markSeen() {
  if (state.data && document.visibilityState === 'visible') state.seenGeneratedAt = state.data.generated_at;
}

function rememberVisit() {
  if (state.seenGeneratedAt) storage.advanceLastVisit(state.seenGeneratedAt);
  writeSession();
}

const isNew = (item) => Number.isFinite(state.baseline) && item.firstSeenMs > state.baseline;

/** "1:58 AM", or "Thu 1:58 AM" when the last visit was another day: the "new since" baseline. */
function baselineLabel(now = Date.now()) {
  if (!Number.isFinite(state.baseline)) return null;
  const time = clockTime(state.baseline);
  if (dayKey(state.baseline) === dayKey(now)) return time;
  return `${new Date(state.baseline).toLocaleDateString([], { weekday: 'short' })} ${time}`;
}

// ── Data ────────────────────────────────────────────────────────────────────
/** Items we can show: an id, a title, an http(s) link and a valid date. */
function isUsable(raw) {
  return Boolean(
    raw &&
      typeof raw.id === 'string' &&
      typeof raw.title === 'string' &&
      ui.safeUrl(raw.url) &&
      Number.isFinite(parseTime(raw.published)),
  );
}

function enrich(raw, sourcesById = state.sourcesById) {
  if (!isUsable(raw)) return null;
  const url = ui.safeUrl(raw.url);
  const publishedMs = parseTime(raw.published);
  const firstSeenMs = parseTime(raw.first_seen);
  const source = sourcesById.get(raw.source);
  const sourceName = source?.name ?? raw.sourceName ?? raw.source ?? 'Unknown source';
  const summary = typeof raw.summary === 'string' ? raw.summary : '';
  return {
    id: raw.id,
    url,
    title: raw.title,
    summary,
    source: raw.source,
    sourceName,
    category: source?.category ?? raw.category ?? 'Other',
    group: source?.group ?? '',
    publishedMs,
    firstSeenMs: Number.isFinite(firstSeenMs) ? firstSeenMs : publishedMs,
    dateEstimated: raw.date_estimated === true,
    searchText: fold(`${raw.title} ${summary} ${sourceName}`),
    watch: [],
  };
}

function sourcesFrom(data) {
  return (Array.isArray(data.sources) ? data.sources : []).filter(
    (s) => s && typeof s.id === 'string' && typeof s.name === 'string',
  );
}

function applyWatch(items) {
  for (const item of items) item.watch = state.matcher ? state.matcher.match(item.title, item.summary) : [];
}

function recomputeWatch() {
  state.matcher = buildMatcher(state.terms);
  applyWatch(state.items);
}

function applyData(data) {
  const isUpdate = Boolean(state.data) && state.data.generated_at !== data.generated_at;
  state.data = data;
  state.pending = null;
  $('new-pill').hidden = true;
  state.sources = sourcesFrom(data);
  state.sourcesById = new Map(state.sources.map((s) => [s.id, s]));
  state.categories = [...new Set(state.sources.map((s) => s.category))];
  state.items = sortItems(data.items.map((raw) => enrich(raw)).filter(Boolean));
  state.itemsById = new Map(state.items.map((item) => [item.id, item]));
  if (!Number.isFinite(state.baseline)) {
    // First visit: everything already published counts as seen; later arrivals are NEW.
    state.baseline = parseTime(data.generated_at);
    writeSession();
  }
  recomputeWatch();
  markSeen();
  renderAll();
  if (isUpdate) blinkWatch();
}

async function fetchFeed() {
  const response = await fetch(`${FEED_URL}?t=${Date.now()}`, { cache: 'no-store' });
  if (!response.ok) {
    const error = new Error(`HTTP ${response.status}`);
    error.status = response.status;
    throw error;
  }
  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error('the feed file is damaged');
  }
  if (!data || data.version !== 1 || !Array.isArray(data.items)) throw new Error('the feed file is in an unknown format');
  return data;
}

async function loadInitial() {
  clearTimeout(state.retryTimer);
  state.lastFetch = Date.now();
  try {
    applyData(await fetchFeed());
    $('feed').setAttribute('aria-busy', 'false');
  } catch (error) {
    $('feed').setAttribute('aria-busy', 'false');
    const firstRun = error.status === 404;
    const offline = navigator.onLine === false;
    let detail;
    if (firstRun) detail = 'There is no data/feed.json yet: wait for the first refresh, or run “python -m owlfeed build” when working locally. This page retries automatically.';
    else if (offline) detail = "You appear to be offline. This page will retry when it can.";
    else detail = `The latest feed couldn't be loaded (${error.message}). Retrying in a minute.`;
    $('feed').replaceChildren(
      ui.emptyState(firstRun ? 'No feed data published yet' : "Couldn't load the feed", detail),
    );
    $('updated').textContent = firstRun ? 'No data yet' : offline ? 'Offline' : 'Update failed';
    $('watch-short').textContent = firstRun ? '—' : offline ? 'Offline' : 'Failed';
    $('watch-btn').dataset.state = 'stale';
    $('watch-btn').setAttribute('aria-label', `Feed status: ${$('updated').textContent.toLowerCase()}`);
    state.retryTimer = setTimeout(loadInitial, 60_000);
  }
}

/** New items in `data` that the reader would actually see with the current view and filters. */
function visibleArrivals(data) {
  const sourcesById = new Map(sourcesFrom(data).map((s) => [s.id, s]));
  const fresh = data.items
    .filter((raw) => isUsable(raw) && !state.itemsById.has(raw.id))
    .map((raw) => enrich(raw, sourcesById));
  applyWatch(fresh);
  return state.prefs.view === 'saved' ? [] : filterItems(fresh, filterContext());
}

async function poll() {
  if (!state.data) return loadInitial();
  state.lastFetch = Date.now();
  let data;
  try {
    data = await fetchFeed();
  } catch {
    return; // keep showing what we have; the next tick tries again
  }
  const latest = state.pending ?? state.data;
  if (data.generated_at === latest.generated_at) return;
  const fresh = visibleArrivals(data).length;
  const label = `${fresh} new ${fresh === 1 ? 'item' : 'items'}`;
  if (window.scrollY < AT_TOP_PX) {
    applyData(data);
    if (fresh) announce(`${label} added`);
  } else {
    state.pending = data;
    renderHeader();
    if (fresh) {
      $('new-pill').textContent = `↑ ${label}`;
      $('new-pill').hidden = false;
    }
  }
}

function applyPending() {
  if (!state.pending) return;
  applyData(state.pending);
  window.scrollTo({ top: 0 });
}

// ── Filtering ───────────────────────────────────────────────────────────────
const isRead = (id) => storage.isRead(id);
const isSaved = (id) => storage.isSaved(id);

function filterContext(view = state.prefs.view, tokens = state.tokens, { unfiltered = false } = {}) {
  return {
    view,
    tokens,
    hiddenCategories: new Set(unfiltered ? [] : state.prefs.hiddenCategories),
    hiddenSources: new Set(unfiltered ? [] : state.prefs.hiddenSources),
    isRead,
    isSaved,
    isNew,
  };
}

/** Saved items come from their snapshots, so they outlive the feed's 7-day window. */
function savedItems() {
  const items = [];
  for (const snapshot of storage.savedItems()) {
    const live = state.itemsById.get(snapshot.id);
    if (live) {
      items.push(live);
      continue;
    }
    const item = enrich({ ...snapshot, published: snapshot.published || snapshot.savedAt });
    if (item) items.push(item);
  }
  applyWatch(items.filter((item) => !state.itemsById.has(item.id)));
  return sortItems(items);
}

function itemsForView(view, saved) {
  return view === 'saved' ? (saved ?? savedItems()) : state.items;
}

function visibleItems() {
  return filterItems(itemsForView(state.prefs.view), filterContext());
}

function renderContext() {
  return { now: Date.now(), matcher: state.matcher, tokens: state.tokens, isRead, isSaved, isNew };
}

// ── Rendering ───────────────────────────────────────────────────────────────
function renderAll() {
  renderSidebar();
  renderHeader();
  renderFeed();
}

// Keep keyboard focus on the same item control when the feed is rebuilt.
function feedFocusKey() {
  const active = document.activeElement;
  if (!active?.closest?.('#feed')) return null;
  const article = active.closest('article[data-id]');
  if (!article) return { id: null, action: null }; // on the empty state
  return { id: article.dataset.id, action: active.dataset.action ?? null };
}

function focusFirstItem() {
  $('feed').querySelector('.item-title a')?.focus({ preventScroll: true });
}

function restoreFeedFocus(key) {
  if (!key) return;
  const article = key.id && articleFor(key.id);
  if (!article) {
    focusFirstItem(); // the focused item is gone (filtered out or expired), or the feed was empty
    return;
  }
  const target = key.action
    ? article.querySelector(`[data-action="${key.action}"]`)
    : article.querySelector('.item-title a');
  target?.focus({ preventScroll: true });
}

function renderFeed() {
  if (!state.data) return;
  const focus = feedFocusKey();
  const list = visibleItems();
  $('feed').dataset.showing = state.prefs.view;
  renderActiveFilters(list.length);
  updateMarkAll();
  if (!list.length) {
    feedRenderer.render([], renderContext());
    const empty = emptyStateFor();
    $('feed').replaceChildren(empty);
    $('sentinel').hidden = true;
    if (focus) {
      // The focused item was the last one in this view: keep focus (and screen readers) in the feed.
      const target = empty.querySelector('[data-empty-action]') ?? empty;
      if (target === empty) empty.tabIndex = -1;
      target.focus({ preventScroll: true });
    }
    return;
  }
  feedRenderer.render(list, renderContext());
  restoreFeedFocus(focus);
}

function scrollToFeedTop() {
  if (window.scrollY > 0) window.scrollTo({ top: 0 });
}

function hasFilters() {
  return Boolean(state.prefs.hiddenCategories.length || state.prefs.hiddenSources.length || state.tokens.length);
}

function emptyStateFor() {
  const clear = { id: 'clear', label: 'Clear filters' };
  const view = state.prefs.view;
  const hiddenByFilters =
    hasFilters() && filterItems(itemsForView(view), filterContext(view, [], { unfiltered: true })).length > 0;
  const query = state.query.trim();
  // Whole-word search found nothing: offer the same words as prefixes, when that finds something.
  const suggestion = query ? prefixSuggestion(query) : null;
  const suggested = suggestion ? filterItems(itemsForView(view), filterContext(view, parseQuery(suggestion))).length : 0;
  if (suggested) {
    state.suggestion = suggestion;
    return ui.emptyState(
      `Nothing matches “${query}” as whole words`,
      `${plural(suggested, 'item')} match if the words can continue (${suggestion}).`,
      { id: 'suggest', label: `Search ${suggestion}` },
    );
  }
  if (hiddenByFilters) {
    return query
      ? ui.emptyState(`Nothing matches ${query.includes('"') ? query : `“${query}”`}`, 'Check the spelling, try fewer words, or clear the search and filters.', clear)
      : ui.emptyState('Nothing matches these filters', 'Clear the search, category or source filters to see more.', clear);
  }
  switch (view) {
    case 'new': {
      // Never a dead end: say when "last visit" was, and point at what is still unread.
      const since = baselineLabel();
      const unread = filterItems(state.items, filterContext('unread', [])).length;
      const waiting = unread ? ` ${plural(unread, 'unread item')} from earlier ${unread === 1 ? 'is' : 'are'} still waiting.` : '';
      const goUnread = unread ? { id: 'unread', label: 'Go to Unread' } : undefined;
      const fresh = freshness();
      if (fresh?.stale) {
        // "Nothing new" can't be confirmed when nothing has been fetched: never show it as an all-clear.
        return ui.emptyState(
          `No refresh since ${clockTime(fresh.generated)}`,
          `Newer reporting may be missing, so this view can’t confirm there’s nothing new.${waiting}`,
          goUnread,
        );
      }
      const title = since ? `Nothing new since ${since}` : 'Nothing new since your last visit';
      return unread
        ? ui.emptyState(title, waiting.trim(), goUnread)
        : ui.emptyState(title, 'New items appear here as the feed refreshes.');
    }
    case 'unread':
      return ui.emptyState("You're all caught up", 'Every item in this view has been read.');
    case 'saved':
      return ui.emptyState('Nothing saved yet', 'Use the star on any item to keep it here, even after it leaves the feed.');
    case 'watchlist':
      return state.terms.length
        ? ui.emptyState('No recent items mention your watchlist terms', 'Matches appear here as new items arrive.')
        : ui.emptyState('Your watchlist is empty', 'Add terms in the sidebar to highlight items that mention them.');
    default:
      return state.items.length
        ? ui.emptyState('Nothing matches these filters', null, clear)
        : ui.emptyState('No items yet', 'Nothing has been published in the last 7 days. This page refreshes automatically.');
  }
}

const VIEW_LABELS = { all: 'All items', new: 'New since last visit', unread: 'Unread', saved: 'Saved', watchlist: 'Watchlist' };

function renderActiveFilters(count) {
  const bar = $('active-filters');
  const parts = [];
  if (state.prefs.view === 'new' && baselineLabel()) parts.push(`New since ${baselineLabel()}`);
  else if (state.prefs.view !== 'all') parts.push(VIEW_LABELS[state.prefs.view]);
  const hiddenCats = state.categories.filter((c) => state.prefs.hiddenCategories.includes(c));
  if (hiddenCats.length) {
    const shown = state.categories.filter((c) => !hiddenCats.includes(c));
    parts.push(shown.length ? `${shown.join(', ')} only` : 'No categories selected');
  }
  const hiddenSources = state.prefs.hiddenSources.filter((id) => state.sourcesById.has(id)).length;
  if (hiddenSources) {
    const shown = state.sources.length - hiddenSources;
    parts.push(
      shown === 1
        ? `Only ${state.sources.find((s) => !state.prefs.hiddenSources.includes(s.id))?.name}`
        : `${hiddenSources} sources hidden`,
    );
  }
  const query = state.query.trim();
  if (query) parts.push(`Search: ${query}`); // shown as typed, so quoted phrases keep one set of quotes
  bar.hidden = parts.length === 0;
  if (!parts.length) return;
  const text = ui.el('span', 'filters-text', `${plural(count, 'item')} · ${parts.join(' · ')}`);
  const clear = ui.el('button', 'link-btn', 'Clear');
  clear.type = 'button';
  clear.dataset.emptyAction = 'reset';
  const nodes = [text];
  // Several bare words match anywhere; say how to match them as a phrase (useless at 0 results).
  if (count > 0 && !query.includes('"') && state.tokens.length > 1) {
    nodes.push(ui.el('span', 'filters-tip', `Tip: "${query}" in quotes matches those words together`));
  }
  // With no results the empty state below offers "Clear filters"; one Clear is enough.
  bar.replaceChildren(...nodes, ...(count > 0 ? [clear] : []));
}

function countBy(items, key) {
  const counts = new Map();
  for (const item of items) counts.set(item[key], (counts.get(item[key]) ?? 0) + 1);
  return counts;
}

function freshness(now = Date.now()) {
  const latest = state.pending ?? state.data;
  const generated = parseTime(latest?.generated_at);
  if (!Number.isFinite(generated)) return null;
  const age = now - generated;
  return {
    generated,
    stale: age > STALE_MS,
    aging: age > AGING_MS && age <= STALE_MS,
    label: `Updated ${updatedLabel(generated, now)}`,
    short: shortAge(age),
  };
}

/** "now", "9m", "3h", "2d": the phone-width freshness label. */
function shortAge(ms) {
  if (ms < 60_000) return 'now';
  if (ms < 3_600_000) return `${Math.floor(ms / 60_000)}m`;
  if (ms < 86_400_000) return `${Math.floor(ms / 3_600_000)}h`;
  return `${Math.floor(ms / 86_400_000)}d`;
}

/** The top bar's watch status: owl eyes, freshness and source health, at every screen size. */
function renderWatch(fresh, now = Date.now()) {
  const button = $('watch-btn');
  const failing = state.sources.filter((s) => s.status !== 'ok');
  const total = state.sources.length;
  const ok = total - failing.length;
  const watchState = !fresh ? 'loading' : fresh.stale ? 'stale' : fresh.aging ? 'aging' : 'fresh';
  if (button.dataset.state !== watchState) button.dataset.state = watchState;
  button.classList.toggle('has-failing', failing.length > 0);
  if (!fresh) return;
  $('updated').textContent = fresh.label;
  $('updated').classList.toggle('is-stale', fresh.stale);
  $('watch-short').textContent = fresh.short;
  $('watch-sources').textContent = total ? `${ok}/${total}` : '';
  const flag = { aging: 'Late', stale: 'Stale' }[watchState] ?? '';
  $('watch-flag').textContent = flag;
  $('watch-flag').hidden = !flag;
  const sourcesText = total ? `, ${ok} of ${total} sources OK` : '';
  const stateText = { aging: 'running late, ', stale: 'stale, ' }[watchState] ?? '';
  button.setAttribute('aria-label', `Feed status: ${stateText}${fresh.label.toLowerCase()}${sourcesText}`);
  button.title = fresh.stale
    ? 'Not refreshed for over an hour. Open for details.'
    : `Feed refreshed ${new Date(fresh.generated).toLocaleString()}`;
  if (!$('watch-panel').hidden) renderWatchPanel(fresh, failing, now);
}

function renderWatchPanel(fresh = freshness(), failing = state.sources.filter((s) => s.status !== 'ok'), now = Date.now()) {
  if (!fresh) return;
  const panel = $('watch-panel');
  const rows = [
    ['Last sweep', `${new Date(fresh.generated).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })} · ${updatedLabel(fresh.generated, now)}`],
    ['Sources', `${state.sources.length - failing.length} of ${state.sources.length} answered`],
    ['Schedule', 'The feed refreshes about every 15 minutes; this page checks every 5.'],
  ];
  const list = ui.el('dl', 'watch-rows');
  for (const [term, detail] of rows) list.append(ui.el('dt', null, term), ui.el('dd', null, detail));
  const nodes = [ui.el('p', `watch-verdict is-${fresh.stale ? 'stale' : fresh.aging ? 'aging' : 'fresh'}`, fresh.stale
    ? 'Stale: newer reporting may be missing.'
    : fresh.aging
      ? 'Running late: the last refresh was over 30 minutes ago.'
      : 'Watching: the feed is up to date.'), list];
  if (failing.length) {
    const failingList = ui.el('ul', 'watch-failing');
    for (const source of failing) {
      const li = ui.el('li');
      li.append(ui.el('strong', null, source.name), ` ${ui.healthTitle(source, now)}`);
      failingList.append(li);
    }
    nodes.push(ui.el('p', 'watch-failing-title', `${failing.length} not answering`), failingList);
  }
  // The status vocabulary, spelled out once where people look for it.
  const legend = ui.el('dl', 'watch-legend');
  for (const [term, detail] of [
    ['Eyes open', 'Fresh: refreshed in the last 30 minutes.'],
    ['Late', '30–60 minutes since the last refresh (it normally runs every 15). Items are still recent.'],
    ['Stale', 'Over an hour since the last refresh. Newer reporting may be missing.'],
    ['31/31', 'Sources that answered on the last refresh. A rust dot marks one that did not.'],
  ]) {
    legend.append(ui.el('dt', null, term === '31/31' ? `${state.sources.length - failing.length}/${state.sources.length}` : term), ui.el('dd', null, detail));
  }
  nodes.push(legend);
  if (fresh.stale || fresh.aging) nodes.push(ownerHint());
  panel.replaceChildren(...nodes);
}

/**
 * For whoever runs this copy of Owlfeed: on GitHub Pages (owner.github.io/repo/) the refresh
 * workflow's page can be linked directly; anywhere else, say where to look.
 */
function ownerHint() {
  const hint = ui.el('p', 'watch-owner');
  hint.append(ui.el('strong', null, 'Running this dashboard? '));
  const owner = location.hostname.match(/^([a-z0-9-]+)\.github\.io$/i)?.[1];
  const repo = location.pathname.split('/').filter(Boolean)[0];
  if (owner && repo) {
    const link = ui.el('a', null, 'Check the Refresh feed workflow');
    link.href = `https://github.com/${owner}/${repo}/actions/workflows/refresh.yml`;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    hint.append(link, '. GitHub pauses schedules in quiet repositories; see the README.');
  } else {
    hint.append('Check the “Refresh feed” workflow in the repository’s Actions tab, and the README’s troubleshooting notes.');
  }
  return hint;
}

const STALE_KEY = 'owlfeed:v1:stale-hidden';
function staleHiddenFor() {
  try {
    return sessionStorage.getItem(STALE_KEY);
  } catch {
    return null;
  }
}

function hideStaleBanner() {
  const latest = (state.pending ?? state.data)?.generated_at;
  try {
    sessionStorage.setItem(STALE_KEY, latest ?? '');
  } catch {
    // sessionStorage unavailable: hide it for this page view only.
  }
  $('stale-banner').hidden = true;
  $('watch-btn').focus(); // the chip still says Stale; continue from there
}

function setWatchPanel(open) {
  $('watch-panel').hidden = !open;
  $('watch-btn').setAttribute('aria-expanded', String(open));
  if (open) renderWatch(freshness()); // pill and panel read the same clock, so their minutes agree
}

/** One blink when a fresh build lands: the owl noticed. */
function blinkWatch() {
  const eyes = $('watch-btn').querySelector('.watch-eyes');
  eyes.classList.remove('is-blinking');
  void eyes.getBoundingClientRect(); // restart the animation
  eyes.classList.add('is-blinking');
}

function renderSidebar() {
  const focused = focusKey(document.activeElement);
  const now = Date.now();
  const saved = savedItems();

  // View counts respect category/source filters (not search).
  for (const view of VIEWS) {
    const count = filterItems(itemsForView(view, saved), filterContext(view, [])).length;
    const button = document.querySelector(`[data-view="${view}"]`);
    button.querySelector('.count').textContent = String(count);
    if (view === state.prefs.view) button.setAttribute('aria-current', 'true');
    else button.removeAttribute('aria-current');
  }
  const since = baselineLabel(now);
  document.querySelector('[data-view="new"]').title = since ? `Items that arrived after ${since}` : '';

  const hiddenSources = new Set(state.prefs.hiddenSources);
  const sourceState = new Map();
  for (const source of state.sources) {
    const entry = sourceState.get(source.category) ?? { shown: 0, total: 0 };
    entry.total += 1;
    if (!hiddenSources.has(source.id)) entry.shown += 1;
    sourceState.set(source.category, entry);
  }
  // Counts follow the source filters, so "Geopolitics 0" when none of its sources are shown.
  const categoryCounts = countBy(state.items.filter((item) => !hiddenSources.has(item.source)), 'category');
  ui.renderCategories($('category-list'), state.categories, new Set(state.prefs.hiddenCategories), categoryCounts, sourceState);
  ui.renderSources($('source-list'), state.sources, {
    hiddenSources: new Set(state.prefs.hiddenSources),
    hiddenCategories: new Set(state.prefs.hiddenCategories),
    counts: countBy(state.items, 'source'),
    now,
    openGroups,
  });
  $('sources-reset').hidden = !state.prefs.hiddenSources.length;
  ui.renderWatchTerms($('watch-terms'), state.terms);
  updateMarkAll();
  restoreFocus(focused);
}

function renderHeader() {
  const fresh = freshness();
  renderWatch(fresh);
  if (fresh) {
    // Written for readers: what they can rely on. The owner's fix lives in the watch report.
    const latest = (state.pending ?? state.data)?.generated_at;
    $('stale-banner').hidden = !fresh.stale || staleHiddenFor() === latest;
    const message = fresh.stale
      ? `This feed was last ${fresh.label.toLowerCase()} (${clockTime(fresh.generated)}). Newer reporting may be missing.`
      : '';
    const text = $('stale-text');
    if (text.textContent !== message) text.textContent = message; // a live region: only real changes
  }
  const newCount = state.data ? filterItems(state.items, filterContext('new', [])).length : 0;
  const chip = $('new-chip');
  chip.hidden = newCount === 0;
  chip.textContent = `${newCount} new`;
  chip.setAttribute('aria-pressed', String(state.prefs.view === 'new'));
}

// Keep keyboard focus on the same sidebar control when the sidebar is rebuilt.
function focusKey(node) {
  if (!node?.dataset) return null;
  for (const attr of ['category', 'source', 'only', 'removeTerm']) {
    if (node.dataset[attr] != null) return [attr, node.dataset[attr]];
  }
  return null;
}

function restoreFocus(key) {
  if (!key) return;
  const [attr, value] = key;
  const kebab = attr.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`);
  document.querySelector(`[data-${kebab}="${CSS.escape(value)}"]`)?.focus();
}

// ── Actions ─────────────────────────────────────────────────────────────────
function savePrefs() {
  storage.setPrefs(state.prefs);
}

function setView(view) {
  state.prefs.view = VIEWS.includes(view) ? view : 'all';
  savePrefs();
  renderAll();
  scrollToFeedTop();
  closeDrawer();
  speak(`${VIEW_LABELS[state.prefs.view]}: ${plural(visibleItems().length, 'item')}`);
}

function toggleListValue(list, value, include) {
  const set = new Set(list);
  if (include) set.add(value);
  else set.delete(value);
  return [...set];
}

function filtersChanged() {
  savePrefs();
  renderAll();
  scrollToFeedTop();
}

function resetFilters(event) {
  state.prefs.hiddenCategories = [];
  state.prefs.hiddenSources = [];
  state.prefs.view = 'all';
  state.query = '';
  state.tokens = [];
  $('search').value = '';
  filtersChanged();
  // The Clear button that had focus is gone. From the keyboard, continue in the search box; after a
  // tap or click, go to the newest item instead, so no on-screen keyboard pops up over the feed.
  if (event?.detail === 0) $('search').focus({ preventScroll: true });
  else focusFirstItem();
}

function articleFor(id) {
  return $('feed').querySelector(`article[data-id="${CSS.escape(id)}"]`);
}

function setReadUI(id, read) {
  const article = articleFor(id);
  if (!article) return;
  article.classList.toggle('is-read', read);
  ui.setActionState(article.querySelector('[data-action="read"]'), read);
}

function markRead(ids, read = true) {
  storage.setRead(ids, read);
  for (const id of ids) setReadUI(id, read);
  renderSidebar();
}

function snapshotOf(item) {
  return {
    id: item.id,
    title: item.title,
    url: item.url,
    summary: item.summary,
    source: item.source,
    sourceName: item.sourceName,
    category: item.category,
    published: new Date(item.publishedMs).toISOString(),
    first_seen: new Date(item.firstSeenMs).toISOString(),
    savedAt: new Date().toISOString(),
  };
}

function toggleSaved(id) {
  const saved = !storage.isSaved(id);
  if (saved) {
    const item = state.itemsById.get(id);
    const snapshot = item ? snapshotOf(item) : unsavedSnapshots.get(id);
    if (!snapshot || !storage.setSaved({ ...snapshot, savedAt: new Date().toISOString() })) return;
  } else {
    const current = storage.savedItems().find((s) => s.id === id);
    if (current) unsavedSnapshots.set(id, current);
    storage.setSaved({ id }, false);
  }
  const button = articleFor(id)?.querySelector('[data-action="save"]');
  if (button) ui.setActionState(button, saved);
  renderSidebar();
}

/** Only the unread items count: marking already-read items is a no-op, and undo must not unread them. */
function unreadVisibleIds() {
  return visibleItems()
    .map((item) => item.id)
    .filter((id) => !storage.isRead(id));
}

function setReadAndRender(ids, read) {
  storage.setRead(ids, read);
  if (state.prefs.view === 'unread') renderAll();
  else {
    for (const id of ids) setReadUI(id, read);
    renderSidebar();
  }
}

function markAllRead() {
  const ids = unreadVisibleIds();
  if (!ids.length) return;
  const hadFocus = document.activeElement?.matches?.('[data-mark-all]');
  setReadAndRender(ids, true);
  updateMarkAll();
  // The button just disabled itself; keyboard focus goes to Undo instead of falling to <body>.
  queueMicrotask(() => {
    if (hadFocus && !$('status-action').hidden) $('status-action').focus({ preventScroll: true });
  });
  announce(`Marked ${plural(ids.length, 'item')} as read`, {
    label: 'Undo',
    run() {
      setReadAndRender(ids, false);
      updateMarkAll();
      announce(`Restored ${plural(ids.length, 'item')} to unread`);
    },
  });
}

/** "Mark 12 read": the scope is part of the label, and the control is off when nothing is unread. */
function updateMarkAll() {
  const count = state.data ? unreadVisibleIds().length : 0;
  for (const button of document.querySelectorAll('[data-mark-all]')) {
    button.disabled = count === 0;
    // "Nothing to mark", not "All read": an empty search or view has nothing unread *shown*,
    // which says nothing about the rest of the feed.
    button.querySelector('.btn-label').textContent = count ? `Mark ${count} read` : 'Nothing to mark';
    const label = count
      ? `Mark all ${plural(count, 'unread item')} in this view as read`
      : 'Nothing unread in this view';
    button.setAttribute('aria-label', label);
    button.title = label;
  }
}

/** Tell screen readers without showing the toast (for results that are already visible on screen). */
let speakTimer = null;
function speak(message) {
  const announcer = $('announcer');
  announcer.textContent = message;
  clearTimeout(speakTimer);
  speakTimer = setTimeout(() => {
    if (announcer.textContent === message) announcer.textContent = '';
  }, 4000);
}

let announceTimer = null;
let toastAction = null;
const TOAST_MS = 4000;
const TOAST_ACTION_MS = 10_000; // long enough to notice a mistake and reach Undo

function hideToast() {
  const toast = $('status');
  if (toast.contains(document.activeElement)) return; // never yank a control out from under focus
  toast.hidden = true;
  toast.classList.remove('has-action');
  toast.setAttribute('aria-hidden', 'true');
  $('status-text').textContent = '';
  $('status-action').hidden = true;
  toastAction = null;
  $('announcer').textContent = '';
}

function scheduleToastHide(ms) {
  clearTimeout(announceTimer);
  announceTimer = setTimeout(hideToast, ms);
}

/**
 * Speak a message and show it in the toast. With an action ({ label, run }), the toast gets a
 * button (e.g. Undo) and stays up longer; without one it is decorative, and only the live region speaks.
 */
function announce(message, action = null) {
  $('announcer').textContent = action ? `${message}. ${action.label} is available in the message at the bottom of the page.` : message;
  const toast = $('status');
  $('status-text').textContent = message;
  toastAction = action;
  const button = $('status-action');
  button.hidden = !action;
  button.textContent = action?.label ?? '';
  toast.classList.toggle('has-action', Boolean(action));
  // An actionable toast has a real button, so it can't be hidden from assistive technology.
  toast.setAttribute('aria-hidden', String(!action));
  toast.hidden = false;
  scheduleToastHide(action ? TOAST_ACTION_MS : TOAST_MS);
}

function runToastAction() {
  const action = toastAction;
  if (!action) return;
  const hadFocus = $('status').contains(document.activeElement);
  toastAction = null;
  action.run(); // replaces the toast with a confirmation that has no button
  if (hadFocus) focusFirstItem(); // the Undo button is gone; continue from the newest item
}

// ── Theme ───────────────────────────────────────────────────────────────────
function effectiveTheme() {
  const explicit = document.documentElement.dataset.theme;
  if (explicit === 'light' || explicit === 'dark') return explicit;
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function syncThemeButton() {
  const next = effectiveTheme() === 'dark' ? 'light' : 'dark';
  $('theme-btn').setAttribute('aria-label', `Switch to ${next} mode`);
  $('theme-btn').title = `Switch to ${next} mode`;
  // Phones: the toggle lives in the drawer as a text link, leaving the top bar to status and search.
  $('theme-btn-drawer').textContent = next === 'dark' ? 'Dark mode' : 'Light mode';
  $('theme-btn-drawer').setAttribute('aria-label', `Switch to ${next} mode`);
}

function toggleTheme() {
  const next = effectiveTheme() === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.theme = next;
  storage.setTheme(next);
  syncThemeButton();
}

// ── Drawer (phones and small tablets) ───────────────────────────────────────
// While closed, the off-screen sidebar is inert (not focusable or announced); while open it
// is modal: the rest of the page is inert until it closes.
const phone = window.matchMedia('(max-width: 600px)');
function syncSearchPlaceholder() {
  // Each width gets a placeholder that fits whole, instead of one cut off mid-word.
  $('search').placeholder = phone.matches ? 'Search' : narrow.matches ? 'Search  ( / )' : 'Search headlines and summaries  ( / )';
}

function syncDrawer() {
  const open = document.body.classList.contains('drawer-open');
  const sidebar = $('sidebar');
  sidebar.inert = narrow.matches && !open;
  $('main').inert = narrow.matches && open;
  // While open on a narrow screen the drawer is a modal dialog; otherwise it is a plain sidebar.
  if (narrow.matches && open) {
    sidebar.setAttribute('role', 'dialog');
    sidebar.setAttribute('aria-modal', 'true');
  } else {
    sidebar.removeAttribute('role');
    sidebar.removeAttribute('aria-modal');
  }
}

function openDrawer() {
  document.body.classList.add('drawer-open');
  $('scrim').hidden = false;
  $('menu-btn').setAttribute('aria-expanded', 'true');
  syncDrawer();
  $('sidebar-close').focus();
}

function closeDrawer({ returnFocus = true } = {}) {
  if (!document.body.classList.contains('drawer-open')) return;
  document.body.classList.remove('drawer-open');
  $('scrim').hidden = true;
  $('menu-btn').setAttribute('aria-expanded', 'false');
  syncDrawer();
  if (returnFocus && narrow.matches) $('menu-btn').focus();
}

// ── Backup / restore ────────────────────────────────────────────────────────
function exportSettings() {
  const blob = new Blob([JSON.stringify(storage.exportData(), null, 2)], { type: 'application/json' });
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = `owlfeed-backup-${new Date().toISOString().slice(0, 10)}.json`;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}

function reloadFromStorage() {
  state.prefs = storage.prefs();
  if (!VIEWS.includes(state.prefs.view)) state.prefs.view = 'all';
  state.terms = storage.watchlist();
  recomputeWatch();
  renderAll();
}

async function importSettings(file) {
  try {
    const result = storage.importData(JSON.parse(await file.text()));
    reloadFromStorage();
    announce(`Restored: ${result.saved} saved items and ${result.terms} watchlist terms added`);
  } catch (error) {
    announce(`Couldn't restore: ${error instanceof SyntaxError ? 'the file is not valid JSON' : error.message}`);
  }
}

// ── Events ──────────────────────────────────────────────────────────────────
function changeWatchlist(change) {
  state.terms = storage.updateWatchlist(change);
  recomputeWatch();
  renderAll();
  if (state.prefs.view === 'watchlist') scrollToFeedTop();
}

function wireEvents() {
  document.querySelector('.view-list').addEventListener('click', (event) => {
    const button = event.target.closest('[data-view]');
    if (button) setView(button.dataset.view);
  });
  $('new-chip').addEventListener('click', () => setView(state.prefs.view === 'new' ? 'all' : 'new'));

  $('category-list').addEventListener('change', (event) => {
    const category = event.target.dataset.category;
    if (category == null) return;
    state.prefs.hiddenCategories = toggleListValue(state.prefs.hiddenCategories, category, !event.target.checked);
    if (event.target.checked) {
      // Checking a category means "show all of it", including sources hidden one by one.
      const ids = new Set(state.sources.filter((s) => s.category === category).map((s) => s.id));
      state.prefs.hiddenSources = state.prefs.hiddenSources.filter((id) => !ids.has(id));
    }
    filtersChanged();
  });

  $('source-list').addEventListener('change', (event) => {
    const source = event.target.dataset.source;
    if (source == null) return;
    state.prefs.hiddenSources = toggleListValue(state.prefs.hiddenSources, source, !event.target.checked);
    filtersChanged();
  });

  $('source-list').addEventListener('click', (event) => {
    const only = event.target.closest('[data-only]')?.dataset.only;
    if (!only) return;
    const source = state.sourcesById.get(only);
    state.prefs.hiddenSources = state.sources.filter((s) => s.id !== only).map((s) => s.id);
    state.prefs.hiddenCategories = state.prefs.hiddenCategories.filter((c) => c !== source?.category);
    filtersChanged();
  });

  // Remember groups the reader opened or closed themselves. (A 'toggle' listener would also see
  // groups the renderer opened, and keep them open after the reason was gone.) Enter and Space
  // on a <summary> arrive as clicks too.
  $('source-list').addEventListener('click', (event) => {
    const summary = event.target.closest('summary');
    const group = summary?.parentElement?.dataset.group;
    if (group == null) return;
    if (summary.parentElement.open) openGroups.delete(group); // about to close
    else openGroups.add(group);
  });

  $('sources-reset').addEventListener('click', () => {
    state.prefs.hiddenSources = [];
    filtersChanged();
    $('source-list').querySelector('[data-source]')?.focus(); // "Show all" hides itself
  });

  let searchTimer = null;
  $('search').addEventListener('input', (event) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      state.query = event.target.value;
      state.tokens = parseQuery(state.query);
      renderFeed();
      scrollToFeedTop();
      if (state.tokens.length) speak(`${plural(visibleItems().length, 'item')} match`);
    }, 150);
  });

  $('watch-form').addEventListener('submit', (event) => {
    event.preventDefault();
    const input = $('watch-input');
    const term = input.value;
    if (!addTerm(state.terms, term).added) {
      // Empty, or already listed: keep what was typed and point at the existing chip.
      const existing = state.terms.find((t) => t.toLowerCase() === normalizeTerm(term).toLowerCase());
      if (existing) {
        const chip = $('watch-terms').querySelector(`[data-remove-term="${CSS.escape(existing)}"]`)?.closest('.chip');
        chip?.classList.remove('is-flash');
        void chip?.offsetWidth; // restart the flash
        chip?.classList.add('is-flash');
        speak(`${existing} is already on your watchlist`);
        input.select();
      }
      return;
    }
    input.value = '';
    changeWatchlist((terms) => addTerm(terms, term).terms);
  });

  $('watch-terms').addEventListener('click', (event) => {
    const term = event.target.closest('[data-remove-term]')?.dataset.removeTerm;
    if (term == null) return;
    changeWatchlist((terms) => removeTerm(terms, term));
    $('watch-input').focus(); // the chip (and its button) no longer exists
  });

  const feed = $('feed');
  feed.addEventListener('click', (event) => {
    const emptyAction = event.target.closest('[data-empty-action]')?.dataset.emptyAction;
    if (emptyAction === 'suggest' && state.suggestion) {
      $('search').value = state.suggestion;
      state.query = state.suggestion;
      state.tokens = parseQuery(state.query);
      renderFeed();
      scrollToFeedTop();
      focusFirstItem();
      speak(`${plural(visibleItems().length, 'item')} match`);
      return;
    }
    if (emptyAction === 'unread') {
      setView('unread');
      focusFirstItem();
      return;
    }
    if (emptyAction) {
      resetFilters(event);
      return;
    }
    const article = event.target.closest('article[data-id]');
    if (!article) return;
    const id = article.dataset.id;
    if (event.target.closest('.item-title a')) {
      markRead([id]);
      return;
    }
    const action = event.target.closest('[data-action]')?.dataset.action;
    if (action === 'save') {
      toggleSaved(id);
      speak(storage.isSaved(id) ? 'Saved' : 'Removed from saved');
    }
    if (action === 'read') {
      const read = !storage.isRead(id);
      markRead([id], read);
      speak(read ? 'Marked as read' : 'Marked as unread');
    }
  });
  feed.addEventListener('auxclick', (event) => {
    if (event.button !== 1) return;
    const id = event.target.closest('.item-title a')?.closest('article[data-id]')?.dataset.id;
    if (id) markRead([id]);
  });

  $('active-filters').addEventListener('click', (event) => {
    if (event.target.closest('[data-empty-action]')) resetFilters(event);
  });
  for (const button of document.querySelectorAll('[data-mark-all]')) {
    button.addEventListener('click', () => {
      markAllRead();
      closeDrawer();
    });
  }
  $('status-action').addEventListener('click', runToastAction);
  $('stale-dismiss').addEventListener('click', hideStaleBanner);
  // Hovering or focusing the toast holds it open; leaving restarts a short countdown.
  for (const [type, ms] of [['pointerenter', null], ['focusin', null], ['pointerleave', 4000], ['focusout', 4000]]) {
    $('status').addEventListener(type, () => {
      if (ms === null) clearTimeout(announceTimer);
      else if (!$('status').hidden) scheduleToastHide(ms);
    });
  }
  for (const button of document.querySelectorAll('[data-theme-toggle]')) button.addEventListener('click', toggleTheme);
  $('watch-btn').addEventListener('click', () => setWatchPanel($('watch-panel').hidden));
  document.addEventListener('click', (event) => {
    if (!$('watch-panel').hidden && !event.target.closest('#watch')) setWatchPanel(false);
  });
  $('new-pill').addEventListener('click', () => {
    applyPending();
    focusFirstItem(); // the pill hides itself; continue from the newest item
  });
  $('menu-btn').addEventListener('click', openDrawer);
  $('sidebar-close').addEventListener('click', () => closeDrawer());
  $('scrim').addEventListener('click', () => closeDrawer());
  $('export-btn').addEventListener('click', exportSettings);
  $('import-btn').addEventListener('click', () => $('import-input').click());
  $('import-input').addEventListener('change', (event) => {
    const [file] = event.target.files;
    if (file) importSettings(file);
    event.target.value = '';
  });
  narrow.addEventListener('change', () => {
    if (!narrow.matches) closeDrawer({ returnFocus: false });
    syncDrawer();
  });

  $('skip-link').addEventListener('click', (event) => {
    event.preventDefault();
    focusFirstItem();
  });
  $('help-btn').addEventListener('click', openHelp);
  $('help-close').addEventListener('click', () => $('help').close());
  $('help').addEventListener('click', (event) => {
    if (event.target === $('help')) $('help').close(); // a click on the backdrop
  });

  document.addEventListener('keydown', (event) => {
    const typing = event.target.closest?.('input, textarea, select, [contenteditable="true"]');
    if (!typing && handleShortcut(event)) {
      event.preventDefault();
      return;
    }
    if (event.key === '/' && !typing) {
      event.preventDefault();
      $('search').focus();
    } else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z' && toastAction && !typing) {
      event.preventDefault();
      runToastAction();
    } else if (event.key === 'Escape') {
      if (!$('watch-panel').hidden) {
        setWatchPanel(false);
        $('watch-btn').focus();
      } else if (document.body.classList.contains('drawer-open')) closeDrawer();
      else if (event.target === $('search') && $('search').value) {
        $('search').value = '';
        state.query = '';
        state.tokens = [];
        renderFeed();
        scrollToFeedTop();
      }
    }
  });

  window.addEventListener(
    'scroll',
    () => {
      if (state.pending && window.scrollY < AT_TOP_PX) applyPending();
    },
    { passive: true },
  );

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') {
      state.hiddenAt = Date.now();
      rememberVisit();
      return;
    }
    if (state.hiddenAt && Date.now() - state.hiddenAt >= VISIT_GAP_MS) {
      startVisit(); // back after a long break: a new visit with a fresh NEW baseline
      if (state.data) renderAll();
    }
    state.hiddenAt = null;
    markSeen();
    if (Date.now() - state.lastFetch >= POLL_MS) poll();
  });
  window.addEventListener('pagehide', rememberVisit);

  // Read/saved/watchlist changes made in another tab.
  storage.listen((key) => {
    if (!state.data) return;
    if (key === null || key === 'watchlist') {
      state.terms = storage.watchlist();
      recomputeWatch();
      renderAll();
    } else if (key === 'read' || key === 'saved') {
      syncItemStates(); // in place, so the reader keeps their scroll position
      renderSidebar();
    }
  });
}

// ── Keyboard shortcuts ──────────────────────────────────────────────────────
function articles() {
  return [...$('feed').querySelectorAll('article[data-id]')];
}

function currentArticle() {
  return document.activeElement?.closest?.('#feed article[data-id]') ?? null;
}

/** The first item whose top edge is below the sticky bars: where j/k start when nothing is focused. */
function firstOnScreen(list) {
  const top = $('main').querySelector('.topbar').getBoundingClientRect().bottom + 40;
  return list.find((article) => article.getBoundingClientRect().bottom > top) ?? list[0];
}

function moveItem(step) {
  const list = articles();
  if (!list.length) return;
  const current = currentArticle();
  const target = current ? list[Math.min(list.length - 1, Math.max(0, list.indexOf(current) + step))] : firstOnScreen(list);
  target.querySelector('.item-title a')?.focus({ preventScroll: true });
  target.scrollIntoView({ block: 'nearest' });
  // Keep the item clear of the sticky top bar and day header.
  const top = target.getBoundingClientRect().top;
  const clearance = $('main').querySelector('.topbar').offsetHeight + 48;
  if (top < clearance) window.scrollBy({ top: top - clearance });
}

function openHelp() {
  if (!$('help').open) $('help').showModal();
}

/** j/k/o/s/m/?: returns true when the key was handled. */
function handleShortcut(event) {
  if (event.ctrlKey || event.metaKey || event.altKey) return false;
  if ($('help').open || document.body.classList.contains('drawer-open')) return false;
  const key = event.key;
  if (key === '?') {
    openHelp();
    return true;
  }
  if (key === 'j' || key === 'k') {
    moveItem(key === 'j' ? 1 : -1);
    return true;
  }
  if (/^[1-5]$/.test(key)) {
    setView(VIEWS[Number(key) - 1]);
    return true;
  }
  if (key === 'n' && state.pending) {
    applyPending();
    focusFirstItem();
    return true;
  }
  const actions = { o: '.item-title a', s: '[data-action="save"]', m: '[data-action="read"]' };
  if (!actions[key]) return false;
  const article = currentArticle();
  if (!article) return false;
  const control = article.querySelector(actions[key]);
  if (!control) return false;
  const focusAction = key === 'o' ? null : control.dataset.action;
  control.click();
  // Keep focus on the item so j/k continue from here (s and m re-render the button's state).
  if (focusAction) articleFor(article.dataset.id)?.querySelector('.item-title a')?.focus({ preventScroll: true });
  return true;
}

function syncItemStates() {
  for (const article of $('feed').querySelectorAll('article[data-id]')) {
    const read = storage.isRead(article.dataset.id);
    article.classList.toggle('is-read', read);
    ui.setActionState(article.querySelector('[data-action="read"]'), read);
    ui.setActionState(article.querySelector('[data-action="save"]'), storage.isSaved(article.dataset.id));
  }
}

function tick() {
  const now = Date.now();
  ui.refreshAges($('feed'), now);
  if (state.data) {
    renderHeader();
  }
  if (document.visibilityState === 'visible' && now - state.lastFetch >= POLL_MS) poll();
}

initVisit();
storage.pruneRead();
syncThemeButton();
syncDrawer();
// Name the modifier Mac users actually press (Cmd+Z works everywhere it says Ctrl+Z).
if (/Mac|iPhone|iPad/.test(navigator.userAgentData?.platform ?? navigator.platform ?? '')) $('undo-mod').textContent = '⌘';
syncSearchPlaceholder();
phone.addEventListener('change', syncSearchPlaceholder);
narrow.addEventListener('change', syncSearchPlaceholder);
wireEvents();
loadInitial();
setInterval(tick, TICK_MS);
