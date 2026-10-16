// Owlfeed dashboard: loads data/feed.json and keeps the page in sync with it.

import { filterItems, fold, parseQuery, sortItems, VIEWS } from './filters.js';
import * as ui from './render.js';
import { createStorage } from './storage.js';
import { parseTime, updatedLabel } from './time.js';
import { addTerm, buildMatcher, removeTerm } from './watchlist.js';

const FEED_URL = 'data/feed.json';
const POLL_MS = 5 * 60_000;
const TICK_MS = 30_000;
const STALE_MS = 60 * 60_000;
// Away from the tab for this long (or a reload after this long) starts a new "visit".
const VISIT_GAP_MS = 30 * 60_000;
const AT_TOP_PX = 200;
const SESSION_KEY = 'owlfeed:v1:visit';

const $ = (id) => document.getElementById(id);
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
    if (firstRun) detail = 'The first refresh publishes it within about 15 minutes. This page will retry automatically.';
    else if (offline) detail = "You appear to be offline. This page will retry when it can.";
    else detail = `The latest feed couldn't be loaded (${error.message}). Retrying in a minute.`;
    $('feed').replaceChildren(
      ui.emptyState(firstRun ? 'No feed data published yet' : "Couldn't load the feed", detail),
    );
    $('updated').textContent = firstRun ? 'Waiting for first refresh' : offline ? 'Offline' : 'Update failed';
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
  return { now: Date.now(), matcher: state.matcher, isRead, isSaved, isNew };
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
  const article = active?.closest?.('#feed article[data-id]');
  if (!article) return null;
  return { id: article.dataset.id, action: active.dataset.action ?? null };
}

function restoreFeedFocus(key) {
  if (!key) return;
  const article = articleFor(key.id);
  const target = key.action
    ? article?.querySelector(`[data-action="${key.action}"]`)
    : article?.querySelector('.item-title a');
  target?.focus({ preventScroll: true });
}

function renderFeed() {
  if (!state.data) return;
  const focus = feedFocusKey();
  const list = visibleItems();
  renderActiveFilters(list.length);
  if (!list.length) {
    feedRenderer.render([], renderContext());
    $('feed').replaceChildren(emptyStateFor());
    $('sentinel').hidden = true;
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
  if (hiddenByFilters) {
    return ui.emptyState('Nothing matches these filters', 'Clear the search, category or source filters to see more.', clear);
  }
  switch (view) {
    case 'new':
      return ui.emptyState('Nothing new since your last visit', 'New items appear here as the feed refreshes.');
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
  if (state.prefs.view !== 'all') parts.push(VIEW_LABELS[state.prefs.view]);
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
  if (state.query.trim()) parts.push(`“${state.query.trim()}”`);
  bar.hidden = parts.length === 0;
  if (!parts.length) return;
  const text = ui.el('span', 'filters-text', `${count} ${count === 1 ? 'item' : 'items'} · ${parts.join(' · ')}`);
  const clear = ui.el('button', 'link-btn', 'Clear');
  clear.type = 'button';
  clear.dataset.emptyAction = 'reset';
  bar.replaceChildren(text, clear);
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
  return { generated, stale: now - generated > STALE_MS, label: `Updated ${updatedLabel(generated, now)}` };
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

  ui.renderCategories($('category-list'), state.categories, new Set(state.prefs.hiddenCategories), countBy(state.items, 'category'));
  ui.renderSources($('source-list'), state.sources, {
    hiddenSources: new Set(state.prefs.hiddenSources),
    hiddenCategories: new Set(state.prefs.hiddenCategories),
    counts: countBy(state.items, 'source'),
    now,
  });
  $('sources-reset').hidden = !state.prefs.hiddenSources.length;
  ui.renderWatchTerms($('watch-terms'), state.terms);
  $('watch-hint').hidden = state.terms.length > 0;
  const fresh = freshness(now);
  ui.renderHealth($('source-health'), state.sources, now, {
    open: Boolean($('source-health').querySelector('details')?.open),
    updated: fresh?.label ?? '',
    stale: fresh?.stale ?? false,
  });
  restoreFocus(focused);
}

function renderHeader() {
  const fresh = freshness();
  const updated = $('updated');
  if (fresh) {
    updated.textContent = fresh.label;
    updated.classList.toggle('is-stale', fresh.stale);
    updated.title = fresh.stale
      ? 'The feed has not refreshed for over an hour. The scheduled refresh may be paused; see the README.'
      : `Feed refreshed ${new Date(fresh.generated).toLocaleString()}`;
    const banner = $('stale-banner');
    banner.hidden = !fresh.stale;
    if (fresh.stale) {
      banner.textContent = `This feed was last ${fresh.label.toLowerCase()}. The scheduled refresh may be paused; check the Actions tab of the Owlfeed repository.`;
    }
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

function resetFilters() {
  state.prefs.hiddenCategories = [];
  state.prefs.hiddenSources = [];
  state.prefs.view = 'all';
  state.query = '';
  state.tokens = [];
  $('search').value = '';
  filtersChanged();
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

function markAllRead() {
  const ids = visibleItems().map((item) => item.id);
  if (!ids.length) return;
  storage.setRead(ids, true);
  if (state.prefs.view === 'unread') renderAll();
  else {
    for (const id of ids) setReadUI(id, true);
    renderSidebar();
  }
  announce(`Marked ${ids.length} ${ids.length === 1 ? 'item' : 'items'} as read`);
}

let announceTimer = null;
function announce(message) {
  // The visible toast is decorative (aria-hidden); a permanently present live region speaks.
  $('announcer').textContent = message;
  const toast = $('status');
  toast.textContent = message;
  toast.hidden = false;
  clearTimeout(announceTimer);
  announceTimer = setTimeout(() => {
    toast.hidden = true;
    toast.textContent = '';
    $('announcer').textContent = '';
  }, 4000);
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
function syncDrawer() {
  const open = document.body.classList.contains('drawer-open');
  $('sidebar').inert = narrow.matches && !open;
  $('main').inert = narrow.matches && open;
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

  $('sources-reset').addEventListener('click', () => {
    state.prefs.hiddenSources = [];
    filtersChanged();
  });

  let searchTimer = null;
  $('search').addEventListener('input', (event) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      state.query = event.target.value;
      state.tokens = parseQuery(state.query);
      renderFeed();
      scrollToFeedTop();
    }, 150);
  });

  $('watch-form').addEventListener('submit', (event) => {
    event.preventDefault();
    const input = $('watch-input');
    const term = input.value;
    input.value = '';
    if (!addTerm(state.terms, term).added) return;
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
    if (event.target.closest('[data-empty-action]')) {
      resetFilters();
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
    if (action === 'save') toggleSaved(id);
    if (action === 'read') markRead([id], !storage.isRead(id));
  });
  feed.addEventListener('auxclick', (event) => {
    if (event.button !== 1) return;
    const id = event.target.closest('.item-title a')?.closest('article[data-id]')?.dataset.id;
    if (id) markRead([id]);
  });

  $('active-filters').addEventListener('click', (event) => {
    if (event.target.closest('[data-empty-action]')) resetFilters();
  });
  $('mark-all-read').addEventListener('click', markAllRead);
  $('theme-btn').addEventListener('click', toggleTheme);
  $('new-pill').addEventListener('click', applyPending);
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

  document.addEventListener('keydown', (event) => {
    const typing = event.target.closest?.('input, textarea, select, [contenteditable="true"]');
    if (event.key === '/' && !typing) {
      event.preventDefault();
      $('search').focus();
    } else if (event.key === 'Escape') {
      if (document.body.classList.contains('drawer-open')) closeDrawer();
      else if (event.target === $('search') && $('search').value) {
        $('search').value = '';
        state.query = '';
        state.tokens = [];
        renderFeed();
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
    const fresh = freshness(now);
    const label = $('source-health').querySelector('.health-updated');
    if (label && fresh) label.textContent = fresh.label;
  }
  if (document.visibilityState === 'visible' && now - state.lastFetch >= POLL_MS) poll();
}

initVisit();
storage.pruneRead();
syncThemeButton();
syncDrawer();
wireEvents();
loadInitial();
setInterval(tick, TICK_MS);
