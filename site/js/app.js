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
const AT_TOP_PX = 200;
const BASELINE_KEY = 'owlfeed:v1:baseline';

const $ = (id) => document.getElementById(id);
const storage = createStorage();

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
  baseline: initBaseline(),
  pending: null,
  lastFetch: 0,
  retryTimer: null,
};
if (!VIEWS.includes(state.prefs.view)) state.prefs.view = 'all';

const feedRenderer = ui.createFeedRenderer($('feed'), $('sentinel'));

// ── Baseline for "new since your last visit" ────────────────────────────────
// The baseline is fixed for the whole tab session (so reloads keep the badges);
// lastVisit is updated whenever the page is hidden or closed.
function initBaseline() {
  let baseline = null;
  try {
    baseline = sessionStorage.getItem(BASELINE_KEY);
  } catch {
    baseline = null;
  }
  if (!baseline) {
    baseline = storage.lastVisit() || new Date().toISOString();
    try {
      sessionStorage.setItem(BASELINE_KEY, baseline);
    } catch {
      // sessionStorage unavailable: badges simply reset on reload.
    }
  }
  return parseTime(baseline);
}

function rememberVisit() {
  storage.setLastVisit(new Date().toISOString());
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

function enrich(raw) {
  if (!isUsable(raw)) return null;
  const url = ui.safeUrl(raw.url);
  const publishedMs = parseTime(raw.published);
  const firstSeenMs = parseTime(raw.first_seen);
  const source = state.sourcesById.get(raw.source);
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
  state.sources = (Array.isArray(data.sources) ? data.sources : []).filter(
    (s) => s && typeof s.id === 'string' && typeof s.name === 'string',
  );
  state.sourcesById = new Map(state.sources.map((s) => [s.id, s]));
  state.categories = [...new Set(state.sources.map((s) => s.category))];
  state.items = sortItems(data.items.map(enrich).filter(Boolean));
  state.itemsById = new Map(state.items.map((item) => [item.id, item]));
  recomputeWatch();
  renderAll();
}

async function fetchFeed() {
  const response = await fetch(`${FEED_URL}?t=${Date.now()}`, { cache: 'no-store' });
  if (!response.ok) {
    const error = new Error(`HTTP ${response.status}`);
    error.status = response.status;
    throw error;
  }
  const data = await response.json();
  if (!data || data.version !== 1 || !Array.isArray(data.items)) throw new Error('unexpected feed format');
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
    $('feed').replaceChildren(
      firstRun
        ? ui.emptyState(
            'No feed data published yet',
            'The first refresh publishes it within about 15 minutes. This page will retry automatically.',
          )
        : ui.emptyState("Couldn't load the feed", `${error.message}. Retrying in a minute.`),
    );
    $('updated').textContent = firstRun ? 'Waiting for first refresh' : 'Offline';
    state.retryTimer = setTimeout(loadInitial, 60_000);
  }
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
  if (data.generated_at === state.data.generated_at) return;
  const fresh = data.items.filter((raw) => isUsable(raw) && !state.itemsById.has(raw.id)).length;
  if (window.scrollY < AT_TOP_PX) {
    applyData(data);
    if (fresh) announce(`${fresh} new ${fresh === 1 ? 'item' : 'items'} added`);
  } else {
    state.pending = data;
    if (fresh) {
      $('new-pill').textContent = `↑ ${fresh} new ${fresh === 1 ? 'item' : 'items'}`;
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
const isNew = (item) => Number.isFinite(state.baseline) && item.firstSeenMs > state.baseline;

function filterContext(view = state.prefs.view, tokens = state.tokens) {
  return {
    view,
    tokens,
    hiddenCategories: new Set(state.prefs.hiddenCategories),
    hiddenSources: new Set(state.prefs.hiddenSources),
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

function itemsForView(view) {
  return view === 'saved' ? savedItems() : state.items;
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

function renderFeed() {
  if (!state.data) return;
  const list = visibleItems();
  renderActiveFilters(list.length);
  if (!list.length) {
    feedRenderer.render([], renderContext());
    $('feed').replaceChildren(emptyStateFor());
    $('sentinel').hidden = true;
    return;
  }
  feedRenderer.render(list, renderContext());
}

function hasFilters() {
  return Boolean(state.prefs.hiddenCategories.length || state.prefs.hiddenSources.length || state.tokens.length);
}

function emptyStateFor() {
  const clear = hasFilters() ? { id: 'clear', label: 'Clear filters' } : null;
  switch (state.prefs.view) {
    case 'new':
      return ui.emptyState('Nothing new since your last visit', 'New items appear here as the feed refreshes.', clear);
    case 'unread':
      return ui.emptyState("You're all caught up", 'Every item in this view has been read.', clear);
    case 'saved':
      return ui.emptyState('Nothing saved yet', 'Use the star on any item to keep it here, even after it leaves the feed.', clear);
    case 'watchlist':
      return state.terms.length
        ? ui.emptyState('No recent items mention your watchlist terms', null, clear)
        : ui.emptyState('Your watchlist is empty', 'Add terms in the sidebar to highlight items that mention them.');
    default:
      return ui.emptyState('Nothing matches these filters', null, clear ?? { id: 'clear', label: 'Clear filters' });
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
    parts.push(shown === 1 ? `Only ${state.sources.find((s) => !state.prefs.hiddenSources.includes(s.id))?.name}` : `${hiddenSources} sources hidden`);
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

function renderSidebar() {
  const focused = focusKey(document.activeElement);
  const now = Date.now();

  // View counts respect category/source filters (not search).
  for (const view of VIEWS) {
    const count = filterItems(itemsForView(view), filterContext(view, [])).length;
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
  ui.renderHealth($('source-health'), state.sources, now);
  restoreFocus(focused);
}

function renderHeader() {
  const now = Date.now();
  const generated = parseTime(state.data?.generated_at);
  const updated = $('updated');
  if (Number.isFinite(generated)) {
    const stale = now - generated > STALE_MS;
    updated.textContent = `Updated ${updatedLabel(generated, now)}`;
    updated.classList.toggle('is-stale', stale);
    updated.title = stale
      ? 'The feed has not refreshed for over an hour. The scheduled refresh may be paused; see the README.'
      : `Feed refreshed ${new Date(generated).toLocaleString()}`;
  }
  const newCount = filterItems(state.items, filterContext('new', [])).length;
  const chip = $('new-chip');
  chip.hidden = newCount === 0;
  chip.textContent = `${newCount} new`;
  chip.setAttribute('aria-pressed', String(state.prefs.view === 'new'));
}

// Keep keyboard focus on the same control when the sidebar is rebuilt.
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
  window.scrollTo({ top: 0 });
  closeDrawer();
}

function toggleListValue(list, value, include) {
  const set = new Set(list);
  if (include) set.add(value);
  else set.delete(value);
  return [...set];
}

function resetFilters() {
  state.prefs.hiddenCategories = [];
  state.prefs.hiddenSources = [];
  state.prefs.view = 'all';
  state.query = '';
  state.tokens = [];
  $('search').value = '';
  savePrefs();
  renderAll();
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

function itemById(id) {
  return state.itemsById.get(id) ?? savedItems().find((item) => item.id === id);
}

function toggleSaved(id) {
  const saved = !storage.isSaved(id);
  const item = itemById(id);
  if (saved && item) {
    storage.setSaved({
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
    });
  } else {
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
  const status = $('status');
  status.textContent = message;
  status.hidden = false;
  clearTimeout(announceTimer);
  announceTimer = setTimeout(() => {
    status.hidden = true;
    status.textContent = '';
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

// ── Drawer (phones) ─────────────────────────────────────────────────────────
function openDrawer() {
  document.body.classList.add('drawer-open');
  $('scrim').hidden = false;
  $('menu-btn').setAttribute('aria-expanded', 'true');
  $('sidebar-close').focus();
}

function closeDrawer() {
  if (!document.body.classList.contains('drawer-open')) return;
  document.body.classList.remove('drawer-open');
  $('scrim').hidden = true;
  $('menu-btn').setAttribute('aria-expanded', 'false');
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

async function importSettings(file) {
  try {
    const result = storage.importData(JSON.parse(await file.text()));
    state.prefs = storage.prefs();
    state.terms = storage.watchlist();
    recomputeWatch();
    renderAll();
    announce(`Restored: ${result.saved} saved items and ${result.terms} watchlist terms added`);
  } catch (error) {
    announce(`Couldn't restore: ${error instanceof SyntaxError ? 'the file is not valid JSON' : error.message}`);
  }
}

// ── Events ──────────────────────────────────────────────────────────────────
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
    savePrefs();
    renderAll();
  });

  $('source-list').addEventListener('change', (event) => {
    const source = event.target.dataset.source;
    if (source == null) return;
    state.prefs.hiddenSources = toggleListValue(state.prefs.hiddenSources, source, !event.target.checked);
    savePrefs();
    renderAll();
  });

  $('source-list').addEventListener('click', (event) => {
    const only = event.target.closest('[data-only]')?.dataset.only;
    if (!only) return;
    const source = state.sourcesById.get(only);
    state.prefs.hiddenSources = state.sources.filter((s) => s.id !== only).map((s) => s.id);
    state.prefs.hiddenCategories = state.prefs.hiddenCategories.filter((c) => c !== source?.category);
    savePrefs();
    renderAll();
  });

  $('sources-reset').addEventListener('click', () => {
    state.prefs.hiddenSources = [];
    savePrefs();
    renderAll();
  });

  let searchTimer = null;
  $('search').addEventListener('input', (event) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      state.query = event.target.value;
      state.tokens = parseQuery(state.query);
      renderFeed();
    }, 150);
  });

  $('watch-form').addEventListener('submit', (event) => {
    event.preventDefault();
    const input = $('watch-input');
    const { terms, added } = addTerm(state.terms, input.value);
    input.value = '';
    if (!added) return;
    state.terms = terms;
    storage.setWatchlist(terms);
    recomputeWatch();
    renderAll();
  });

  $('watch-terms').addEventListener('click', (event) => {
    const term = event.target.closest('[data-remove-term]')?.dataset.removeTerm;
    if (term == null) return;
    state.terms = removeTerm(state.terms, term);
    storage.setWatchlist(state.terms);
    recomputeWatch();
    renderAll();
  });

  const feed = $('feed');
  feed.addEventListener('click', (event) => {
    const emptyAction = event.target.closest('[data-empty-action]');
    if (emptyAction) {
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
    const link = event.target.closest('.item-title a');
    const id = link?.closest('article[data-id]')?.dataset.id;
    if (id) markRead([id]);
  });

  $('active-filters').addEventListener('click', (event) => {
    if (event.target.closest('[data-empty-action]')) resetFilters();
  });
  $('mark-all-read').addEventListener('click', markAllRead);
  $('theme-btn').addEventListener('click', toggleTheme);
  $('new-pill').addEventListener('click', applyPending);
  $('menu-btn').addEventListener('click', openDrawer);
  $('sidebar-close').addEventListener('click', closeDrawer);
  $('scrim').addEventListener('click', closeDrawer);
  $('export-btn').addEventListener('click', exportSettings);
  $('import-input').addEventListener('change', (event) => {
    const [file] = event.target.files;
    if (file) importSettings(file);
    event.target.value = '';
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

  window.addEventListener('scroll', () => {
    if (state.pending && window.scrollY < AT_TOP_PX) applyPending();
  }, { passive: true });

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') rememberVisit();
    else if (Date.now() - state.lastFetch >= POLL_MS) poll();
  });
  window.addEventListener('pagehide', rememberVisit);
}

function tick() {
  const now = Date.now();
  ui.refreshAges($('feed'), now);
  if (state.data) renderHeader();
  if (document.visibilityState === 'visible' && now - state.lastFetch >= POLL_MS) poll();
}

storage.pruneRead();
syncThemeButton();
wireEvents();
loadInitial();
setInterval(tick, TICK_MS);
