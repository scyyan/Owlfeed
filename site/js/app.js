// Owlfeed dashboard: loads data/feed.json and keeps the page in sync with it.

import { filterItems, fold, matchesQuery, parseQuery, prefixSuggestion, sortItems, VIEWS } from './filters.js';
import * as ui from './render.js';
import { createStorage, DENSITIES } from './storage.js';
import { clockTime, DAY, dayKey, HOUR, MINUTE, momentLabel, parseTime, updatedLabel } from './time.js';
import { addTerm, buildMatcher, normalizeTerm, removeTerm } from './watchlist.js';

const FEED_URL = 'data/feed.json';
const POLL_MS = 5 * 60_000;
const TICK_MS = 30_000;
const RETRY_MS = 60_000; // after a failed load
const STALE_MS = 60 * 60_000;
// The feed refreshes every 15 minutes; past this it is running late (but not yet stale).
const AGING_MS = 30 * 60_000;
// Away from the tab for this long (or a reload after this long) starts a new "visit".
const VISIT_GAP_MS = 30 * 60_000;
// A first visit has no "last visit": count the last day's arrivals as new, so the New view starts useful.
const FIRST_VISIT_MS = 24 * 60 * 60_000;
const AT_TOP_PX = 200;
const SESSION_KEY = 'owlfeed:v1:visit';

const $ = (id) => document.getElementById(id);
const plural = (count, noun) => `${count} ${count === 1 ? noun : `${noun}s`}`;
const storage = createStorage();
const narrow = window.matchMedia('(max-width: 900px)');
const midWidth = window.matchMedia('(max-width: 1100px)');

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
  firstVisit: false, // no earlier visit: the baseline is the last 24 hours instead
  watchTerm: null, // in the Watchlist hits view: show only this term's hits
  showAllHits: false, // briefing views: all watchlist hits pinned, not just the newest few
  widened: null, // { from: 'ransom', to: 'ransom*' } when a whole-word search found nothing and its prefix form did
  exactQuery: null, // a query the reader asked to keep whole-word, even with no results
  suggestion: null, // the prefix form ("ransom*") offered by the current empty state or filter bar
  upgradesOpen: false, // the watchlist's "could catch more" list is expanded
  seenGeneratedAt: null, // generated_at of the newest build shown while the page was visible
  hiddenAt: null,
  pending: null,
  lastFetch: 0,
  retryTimer: null,
};
if (!VIEWS.includes(state.prefs.view)) state.prefs.view = 'all';
applyDefaultDensity();

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
    sessionStorage.setItem(SESSION_KEY, JSON.stringify({ baseline, first: state.firstVisit, at: Date.now() }));
  } catch {
    // sessionStorage unavailable: a reload simply starts a new visit.
  }
}

function startVisit() {
  storage.invalidate('lastVisit');
  state.baseline = parseTime(storage.lastVisit()); // NaN on a first visit: set from the first data
  state.firstVisit = false;
  writeSession();
}

function initVisit() {
  const session = readSession();
  if (session && Date.now() - session.at < VISIT_GAP_MS) {
    state.baseline = parseTime(session.baseline); // a reload keeps this visit's NEW badges
    state.firstVisit = session.first === true;
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

/**
 * What NEW is measured from, in one phrase used by the summary line, the empty state and the
 * sidebar tooltip: "since your last visit, 1:58 PM", or on a first visit "in the 24 hours before
 * the last update" (measured from the build, so a stale feed's rows can still say "2d ago").
 */
function newScope(now = Date.now()) {
  if (state.firstVisit) return 'in the 24 hours before the last update';
  const since = baselineLabel(now);
  return since ? `since your last visit, ${since}` : 'since your last visit';
}

// A first visit has no seen-before build, and a fresh fetch "first sees" a whole week at once, so
// there NEW means published in the last 24 hours, plus anything that arrives while the page is open.
const isNew = (item) =>
  Number.isFinite(state.baseline) &&
  (state.firstVisit
    ? item.publishedMs > state.baseline || item.firstSeenMs > state.baseline + FIRST_VISIT_MS
    : item.firstSeenMs > state.baseline);

/** "1:58 AM", or "Thu 1:58 AM" when the last visit was another day: the "new since" baseline. */
function baselineLabel(now = Date.now()) {
  if (!Number.isFinite(state.baseline) || state.firstVisit) return null;
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
    // First visit: the last day's arrivals count as NEW, so "New since last visit" isn't an empty
    // view next to hundreds of unread items. From the next visit on, the real baseline applies.
    state.baseline = parseTime(data.generated_at) - FIRST_VISIT_MS;
    state.firstVisit = true;
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
    state.retryTimer = setTimeout(loadInitial, RETRY_MS);
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
  const label = `${fresh} just arrived`;
  if (window.scrollY < AT_TOP_PX) {
    applyData(data);
    if (fresh) announce(`${plural(fresh, 'new item')} added`);
  } else {
    state.pending = data;
    renderHeader();
    if (fresh) {
      $('new-pill').textContent = `↑ ${label}`;
      $('new-pill').setAttribute('aria-label', `Show ${plural(fresh, 'item')} that just arrived`);
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

function filterContext(view = state.prefs.view, tokens = state.tokens, { unfiltered = false, watchTerm = state.watchTerm } = {}) {
  return {
    view,
    tokens,
    watchTerm: unfiltered ? null : watchTerm,
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
  return { now: Date.now(), view: state.prefs.view, matcher: state.matcher, tokens: state.tokens, isRead, isSaved, isNew };
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
  updateMarkAll(list);
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
  if (BRIEFING_VIEWS.has(state.prefs.view)) {
    // A briefing: the newest watchlist hits first (all of them on request; the rest stay in the
    // timeline below), a one-line summary above, and a finish line that can close it out.
    const hits = list.filter((item) => item.watch.length);
    const pinned = state.showAllHits ? hits : hits.slice(0, PINNED_LIMIT);
    const pinnedIds = new Set(pinned.map((item) => item.id));
    const rest = pinned.length ? list.filter((item) => !pinnedIds.has(item.id)) : list;
    feedRenderer.render(rest, renderContext(), {
      pinned,
      pinnedDetail: pinnedDetail(hits.length),
      pinnedFooter: hits.length > PINNED_LIMIT ? pinnedToggle(hits.length) : null,
      lead: briefingSummary(list, hits),
      end: caughtUpNote(list),
    });
  } else {
    feedRenderer.render(list, renderContext());
  }
  restoreFeedFocus(focus);
}

const BRIEFING_VIEWS = new Set(['new', 'unread']);
const PINNED_LIMIT = 5;

function pinnedDetail(total) {
  if (state.showAllHits || total <= PINNED_LIMIT) return total === 1 ? '1 hit' : `All ${total}, newest first`;
  return `Newest ${PINNED_LIMIT} of ${total}`;
}

function pinnedToggle(total) {
  const button = ui.el('button', 'link-btn pinned-toggle', state.showAllHits ? `Show only the newest ${PINNED_LIMIT}` : `Show all ${total} hits here`);
  button.type = 'button';
  button.dataset.feedAction = 'toggle-hits';
  if (!state.showAllHits) button.title = 'The other hits are in the timeline below, in time order';
  return button;
}

/**
 * "129 new · 12 watchlist hits · 80 Cyber · 49 Geopolitics", as a list (screen readers hear the
 * parts apart). The hits and category counts are filters: hits opens the Watchlist hits view,
 * a category shows that category alone within this view.
 */
function briefingSummary(list, pinned) {
  const box = ui.el('ul', 'briefing');
  box.setAttribute('aria-label', 'Briefing summary');
  const part = (count, label, action) => {
    const li = ui.el('li', 'briefing-part');
    const node = action ? ui.el('button', 'briefing-link') : ui.el('span');
    if (action) {
      node.type = 'button';
      Object.assign(node.dataset, action);
    }
    node.append(ui.el('strong', null, String(count)), ` ${label}`);
    li.append(node);
    return li;
  };
  const parts = [];
  const fresh = freshness();
  if (fresh?.stale) {
    // The stale banner folds in here for briefings: one line, before the counts it qualifies.
    const li = ui.el('li', 'briefing-part briefing-stale', `Stale: last update ${momentLabel(fresh.generated)}, ${updatedLabel(fresh.generated)}`);
    parts.push(li);
  }
  const first = part(list.length, state.prefs.view === 'new' ? 'new' : 'unread');
  if (state.prefs.view === 'new') first.firstChild.append(ui.el('span', 'briefing-scope', ` ${newScope()}`));
  parts.push(first);
  if (state.terms.length) {
    const label = pinned.length === 1 ? 'watchlist hit' : 'watchlist hits';
    parts.push(part(pinned.length, label, pinned.length ? { feedAction: 'briefing-hits' } : null));
  }
  const byCategory = countBy(list, 'category');
  const shown = state.categories.filter((category) => byCategory.get(category));
  for (const category of shown) {
    const action = shown.length > 1 ? { feedAction: 'briefing-category', onlyCategory: category } : null;
    parts.push(part(byCategory.get(category), category, action));
  }
  box.append(...parts);
  return box;
}

// Whether an item matches a prefix variant ("ransom*") depends only on its text, so the answer is
// kept per item. Items are rebuilt when new data arrives, which drops the cache with them.
const variantHits = new WeakMap(); // item -> Map(variant -> matched?)
const variantMatchers = new Map(); // variant -> matcher

function matchesVariant(item, variant) {
  let byVariant = variantHits.get(item);
  if (!byVariant) variantHits.set(item, (byVariant = new Map()));
  if (!byVariant.has(variant)) {
    let matcher = variantMatchers.get(variant);
    if (!matcher) variantMatchers.set(variant, (matcher = buildMatcher([variant])));
    byVariant.set(variant, matcher.match(item.title, item.summary).length > 0);
  }
  return byVariant.get(variant);
}

/**
 * Whole-word terms can miss spellings ("Zelensky" vs "Zelenskyy"). For each term whose prefix
 * form would catch more, the watchlist offers the upgrade: { variant, extra }.
 */
function termUpgrades(termCounts, pool) {
  const upgrades = new Map();
  for (const term of state.terms) {
    if (term.endsWith('*') || term.replace(/\s+/g, '').length < 3) continue;
    const variant = `${term}*`;
    if (state.terms.some((t) => t.toLowerCase() === variant.toLowerCase())) continue;
    const total = pool.filter((item) => matchesVariant(item, variant)).length;
    const extra = total - (termCounts.get(term) ?? 0);
    if (extra > 0) upgrades.set(term, { variant, extra });
  }
  return upgrades;
}

/**
 * The end of a briefing. "Caught up" only when nothing in the view is unread; otherwise the list
 * ends with the one action that closes it out (scoped, with Undo). Never an all-clear the data
 * can't back: while stale it says so.
 */
function caughtUpNote(list = visibleItems()) {
  const fresh = freshness();
  if (!fresh) return null;
  const time = momentLabel(fresh.generated);
  const unread = unreadVisibleIds(list).length;
  const note = ui.el('div', 'caught-up');
  note.setAttribute('role', 'note');
  let title;
  if (unread) title = `End of the list · ${plural(unread, 'unread item')}`;
  else title = fresh.stale ? `Caught up to the last update, ${time}` : `You’re caught up to ${time}`;
  let detail;
  if (fresh.stale) detail = `The feed hasn’t refreshed since ${time}, so newer reporting may be missing.`;
  else if (unread) detail = 'Mark them read to start your next briefing from here.';
  else detail = 'New reporting will appear at the top as the feed refreshes.';
  note.append(ui.el('p', 'caught-up-title', title), ui.el('p', 'caught-up-detail', detail));
  if (unread) {
    const button = ui.el('button', 'btn caught-up-action', `Mark these ${unread} read`);
    button.type = 'button';
    button.dataset.feedAction = 'mark-view';
    note.append(button);
  }
  return note;
}

/** Keep the briefing's summary and finish line true after reads, without re-rendering the list. */
function refreshBriefing(list) {
  if (!state.data || !BRIEFING_VIEWS.has(state.prefs.view)) return;
  const feed = $('feed');
  const lead = feed.querySelector('.briefing');
  const end = feed.querySelector('.caught-up');
  if (!lead && !end) return;
  list ??= visibleItems();
  if (lead) lead.replaceWith(briefingSummary(list, list.filter((item) => item.watch.length)));
  if (end) {
    const hadFocus = end.contains(document.activeElement);
    const next = caughtUpNote(list);
    end.replaceWith(next);
    if (hadFocus) (next.querySelector('button') ?? next).focus?.({ preventScroll: true });
  }
}

function scrollToFeedTop() {
  if (window.scrollY > 0) window.scrollTo({ top: 0 });
}

function hasFilters() {
  return Boolean(
    state.prefs.hiddenCategories.length || state.prefs.hiddenSources.length || state.tokens.length || state.watchTerm,
  );
}

function emptyStateFor() {
  const view = state.prefs.view;
  // Only the search is narrowing things down: say so, and clear just that.
  const searchOnly = state.tokens.length && !state.prefs.hiddenCategories.length && !state.prefs.hiddenSources.length && !state.watchTerm;
  const clear = searchOnly ? { id: 'clear-search', label: 'Clear search' } : { id: 'clear', label: 'Clear filters' };
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
    // Name the one filter that is hiding matches, and offer to lift just that.
    const lift = liftingFilter(view);
    if (lift) {
      const matches = lift.count === 1 ? '1 match is' : `${lift.count} matches are`;
      return ui.emptyState(
        query ? `Nothing matches ${query.includes('"') ? query : `“${query}”`} here` : 'Nothing matches these filters',
        `${matches} hidden by ${lift.reason}.`,
        { id: `lift-${lift.id}`, label: lift.label },
      );
    }
    // The view itself can be what is narrowing the search (Watchlist hits, Unread, Saved, New): when
    // the same search finds items in All items, say that instead of blaming the spelling.
    const inAll = query && view !== 'all' ? filterItems(itemsForView('all'), filterContext('all')).length : 0;
    if (inAll) {
      return ui.emptyState(
        `Nothing in ${VIEW_LABELS[view]} matches ${query.includes('"') ? query : `“${query}”`}`,
        `${plural(inAll, 'item')} ${inAll === 1 ? 'matches' : 'match'} in All items.`,
        { id: 'search-all', label: 'Search all items' },
      );
    }
    return query
      ? ui.emptyState(
          `Nothing matches ${query.includes('"') ? query : `“${query}”`}`,
          searchOnly ? 'Check the spelling or try fewer words.' : 'Check the spelling, try fewer words, or clear the search and filters.',
          clear,
        )
      : ui.emptyState('Nothing matches these filters', 'Clear the search, category or source filters to see more.', clear);
  }
  switch (view) {
    case 'new': {
      // Never a dead end: say when "last visit" was, and point at what is still unread.
      const since = baselineLabel();
      const unread = filterItems(state.items, filterContext('unread', [])).length;
      const waiting = unread ? ` ${plural(unread, 'unread item')} from earlier ${unread === 1 ? 'is' : 'are'} still waiting.` : '';
      const fresh = freshness();
      if (fresh?.stale) {
        // "Nothing new" can't be confirmed when nothing has been fetched: never show it as an all-clear.
        // The reader's best move is to read what is here, newest first, so that is the button.
        return ui.emptyState(
          `No refresh since ${momentLabel(fresh.generated)}`,
          `That was ${updatedLabel(fresh.generated)}. Newer reporting may be missing, so this view can’t confirm there’s nothing new.${waiting}`,
          unread ? { id: 'unread', label: 'Show Unread, newest first' } : undefined,
        );
      }
      const goUnread = unread ? { id: 'unread', label: 'Go to Unread' } : undefined;
      const title = `Nothing new ${newScope()}`;
      return unread
        ? ui.emptyState(title, waiting.trim(), goUnread)
        : ui.emptyState(title, 'New items appear here as the feed refreshes.');
    }
    case 'unread':
      return ui.emptyState("You're all caught up", 'Every item in this view has been read.');
    case 'saved':
      return ui.emptyState('Nothing saved yet', 'Use the star on any item to keep it here, even after it leaves the feed.');
    case 'watchlist':
      if (state.watchTerm) {
        return ui.emptyState(`No recent items mention ${state.watchTerm}`, 'Matches appear here as new items arrive.', { id: 'all-hits', label: 'Show all watchlist hits' });
      }
      return state.terms.length
        ? ui.emptyState('No recent items mention your watchlist terms', 'Matches appear here as new items arrive.')
        : ui.emptyState('Your watchlist is empty', 'Add terms in the sidebar to highlight items that mention them.');
    default:
      return state.items.length
        ? ui.emptyState('Nothing matches these filters', null, clear)
        : ui.emptyState('No items yet', 'Nothing has been published in the last 7 days. This page refreshes automatically.');
  }
}

/** The first single filter (watchlist term, categories, sources) whose removal brings matches back. */
function liftingFilter(view) {
  const hiddenCats = state.categories.filter((c) => state.prefs.hiddenCategories.includes(c));
  const options = [
    state.watchTerm && { id: 'term', label: 'Show all watchlist hits', reason: `the term filter (${state.watchTerm})`, change: (ctx) => { ctx.watchTerm = null; } },
    hiddenCats.length && {
      id: 'categories',
      label: `Show ${hiddenCats.join(', ')} too`,
      reason: `the category filter (${hiddenCats.join(', ')} hidden)`,
      change: (ctx) => { ctx.hiddenCategories = new Set(); },
    },
    state.prefs.hiddenSources.length && { id: 'sources', label: 'Show all sources', reason: 'hidden sources', change: (ctx) => { ctx.hiddenSources = new Set(); } },
  ].filter(Boolean);
  for (const option of options) {
    const ctx = filterContext(view);
    option.change(ctx);
    const count = filterItems(itemsForView(view), ctx).length;
    if (count) return { ...option, count };
  }
  return null;
}

const PHONE_TAB_VIEWS = new Set(['all', 'new', 'unread', 'watchlist']); // the views with a tab in the phone's bottom bar
const VIEW_LABELS = { all: 'All items', new: 'New since last visit', unread: 'Unread', saved: 'Saved', watchlist: 'Watchlist hits' };

/**
 * What is narrowing the timeline, one removable token per constraint (view, watchlist term,
 * categories, sources, search), so the reader can drop one and keep the rest. "Clear all" joins
 * them once there are two or more.
 */
function activeFilterParts() {
  const parts = [];
  // Briefing views name themselves in their summary line (and the sidebar), so no view token there.
  // On phones a view with a tab in the bottom bar is named there, so it gets no token of its own.
  const namedByTab = phone.matches && PHONE_TAB_VIEWS.has(state.prefs.view);
  if (state.prefs.view !== 'all' && !BRIEFING_VIEWS.has(state.prefs.view) && !namedByTab) parts.push({ id: 'view', label: VIEW_LABELS[state.prefs.view] });
  if (state.prefs.view === 'watchlist' && state.watchTerm) parts.push({ id: 'term', label: `Term: ${state.watchTerm}` });
  const hiddenCats = state.categories.filter((c) => state.prefs.hiddenCategories.includes(c));
  if (hiddenCats.length) {
    const shown = state.categories.filter((c) => !hiddenCats.includes(c));
    parts.push({ id: 'categories', label: shown.length ? `${shown.join(', ')} only` : 'No categories selected' });
  }
  const hiddenSources = state.prefs.hiddenSources.filter((id) => state.sourcesById.has(id)).length;
  if (hiddenSources) {
    const shown = state.sources.length - hiddenSources;
    parts.push({
      id: 'sources',
      label:
        shown === 1
          ? `Only ${state.sources.find((s) => !state.prefs.hiddenSources.includes(s.id))?.name}`
          : `${hiddenSources} sources hidden`,
    });
  }
  const query = state.query.trim();
  // As typed, so quoted phrases keep one set of quotes; a widened search shows what it really ran.
  if (query) parts.push({ id: 'search', label: `Search: ${state.widened ? state.widened.to : query}` });
  return parts;
}

function renderActiveFilters(count) {
  const bar = $('active-filters');
  const parts = activeFilterParts();
  // Nothing narrowing the view: phones still show where you are ("All items · 328"); wider screens
  // have the sidebar for that, so CSS hides this idle form there.
  // In a briefing the summary line already says where you are: no idle bar there.
  bar.hidden = !parts.length && BRIEFING_VIEWS.has(state.prefs.view) && count > 0;
  bar.classList.toggle('is-idle', parts.length === 0);
  if (bar.hidden) {
    bar.replaceChildren();
    return;
  }
  if (!parts.length) {
    bar.replaceChildren(ui.el('span', 'filters-count', plural(count, 'item')), ui.el('span', 'filters-view', VIEW_LABELS[state.prefs.view]));
    return;
  }
  const tokens = ui.el('ul', 'filter-tokens');
  tokens.setAttribute('aria-label', 'Active filters');
  for (const part of parts) {
    const li = ui.el('li');
    const button = ui.el('button', 'filter-token');
    button.type = 'button';
    button.dataset.clearFilter = part.id;
    button.setAttribute('aria-label', `Remove filter: ${part.label}`);
    button.append(ui.el('span', 'filter-token-label', part.label), ui.icon('close'));
    li.append(button);
    tokens.append(li);
  }
  // Briefing views carry the count in their summary line; one count per region is enough.
  const nodes = BRIEFING_VIEWS.has(state.prefs.view) && count > 0 ? [tokens] : [ui.el('span', 'filters-count', plural(count, 'item')), tokens];
  // With no results the empty state below offers the next step; one exit is enough there.
  if (parts.length > 1 && count > 0) {
    const clear = ui.el('button', 'link-btn filters-clear', 'Clear all');
    clear.type = 'button';
    clear.dataset.emptyAction = 'reset';
    nodes.push(clear);
  }
  if (state.widened) {
    // Said once, beside the search token: why these results, and the way back to strict.
    const note = ui.el('span', 'filters-widened', `No whole-word matches for “${state.widened.from}”, so showing ${state.widened.to}. `);
    const exact = ui.el('button', 'link-btn', 'Search exactly');
    exact.type = 'button';
    exact.dataset.emptyAction = 'exact';
    note.append(exact);
    nodes.push(note);
  }
  // Saved is the reader's own archive: when category or source filters hide some of it, say how
  // many, with the way to show them.
  if (state.prefs.view === 'saved' && count > 0 && (state.prefs.hiddenCategories.length || state.prefs.hiddenSources.length)) {
    const unfiltered = filterContext('saved');
    unfiltered.hiddenCategories = new Set();
    unfiltered.hiddenSources = new Set();
    const hidden = filterItems(itemsForView('saved'), unfiltered).length - count;
    if (hidden > 0) {
      const note = ui.el('span', 'filters-widened', `${plural(hidden, 'saved item')} hidden by your filters. `);
      const show = ui.el('button', 'link-btn', 'Show them');
      show.type = 'button';
      show.dataset.emptyAction = 'show-saved';
      note.append(show);
      nodes.push(note);
    }
  }
  // Whole words can miss variants ("Zelensky" vs "Zelenskyy"): when the prefix form finds more,
  // say how many more, one click away. Otherwise, for several bare words, the phrase tip.
  const query = state.query.trim();
  const suggestion = count > 0 && query ? prefixSuggestion(query) : null;
  const extra = suggestion
    ? filterItems(itemsForView(state.prefs.view), filterContext(state.prefs.view, parseQuery(suggestion))).length - count
    : 0;
  if (extra > 0) {
    state.suggestion = suggestion;
    const hint = ui.el('button', 'link-btn filters-variant', `+${extra} more as ${suggestion}`);
    hint.type = 'button';
    hint.dataset.emptyAction = 'suggest';
    hint.title = 'Words ending in * also match longer words';
    nodes.push(hint);
  } else if (count > 0 && !query.includes('"') && state.tokens.length > 1) {
    nodes.push(ui.el('span', 'filters-tip', `Tip: "${query}" in quotes matches those words together`));
  }
  bar.replaceChildren(...nodes);
}

/** Drop one constraint and keep the rest. */
function clearFilter(id, event) {
  const order = activeFilterParts().map((part) => part.id); // before the change: where this token sat
  if (id === 'view') {
    state.prefs.view = 'all';
    state.watchTerm = null;
  } else if (id === 'term') state.watchTerm = null;
  else if (id === 'categories') state.prefs.hiddenCategories = [];
  else if (id === 'sources') state.prefs.hiddenSources = [];
  else if (id === 'search') clearSearchState();
  filtersChanged();
  // Focus moves to the token that took this one's place, or (none left) where Clear would go.
  const remaining = [...$('active-filters').querySelectorAll('[data-clear-filter]')];
  const next = remaining.find((button) => order.indexOf(button.dataset.clearFilter) > order.indexOf(id)) ?? remaining.at(-1);
  if (next) next.focus({ preventScroll: true });
  else if (event?.detail === 0) $('search').focus({ preventScroll: true });
  else focusFirstItem();
  speak(`Filter removed. ${plural(visibleItems().length, 'item')} shown`);
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
  if (ms < MINUTE) return 'now';
  if (ms < HOUR) return `${Math.floor(ms / MINUTE)}m`;
  if (ms < DAY) return `${Math.floor(ms / HOUR)}h`;
  return `${Math.floor(ms / DAY)}d`;
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

  // Every count follows the search, so the sidebar and the timeline never disagree. While a search
  // is active the counts take the search blue: they are matches, not totals.
  $('sidebar').classList.toggle('is-searching', state.tokens.length > 0);
  for (const view of VIEWS) {
    const count = filterItems(itemsForView(view, saved), filterContext(view, state.tokens, { watchTerm: null })).length;
    // The sidebar row and, on phones, its tab in the bottom bar.
    for (const button of document.querySelectorAll(`[data-view="${view}"], [data-tab="${view}"]`)) {
      button.querySelector('.count').textContent = String(count);
      if (view === state.prefs.view) button.setAttribute('aria-current', 'true');
      else button.removeAttribute('aria-current');
    }
  }
  const since = baselineLabel(now);
  document.querySelector('[data-view="new"]').title = state.firstVisit
    ? 'First visit: items that arrived in the last 24 hours'
    : since
      ? `Items that arrived after ${since}`
      : '';

  const hiddenSources = new Set(state.prefs.hiddenSources);
  const sourceState = new Map();
  for (const source of state.sources) {
    const entry = sourceState.get(source.category) ?? { shown: 0, total: 0 };
    entry.total += 1;
    if (!hiddenSources.has(source.id)) entry.shown += 1;
    sourceState.set(source.category, entry);
  }
  // Counts follow the source filters (so "Geopolitics 0" when none of its sources are shown) and the search.
  const matching = state.tokens.length ? state.items.filter((item) => matchesQuery(item.searchText, state.tokens)) : state.items;
  const categoryCounts = countBy(matching.filter((item) => !hiddenSources.has(item.source)), 'category');
  ui.renderCategories($('category-list'), state.categories, new Set(state.prefs.hiddenCategories), categoryCounts, sourceState, countBy(matching, 'category'));
  ui.renderSources($('source-list'), state.sources, {
    hiddenSources: new Set(state.prefs.hiddenSources),
    hiddenCategories: new Set(state.prefs.hiddenCategories),
    counts: countBy(matching, 'source'),
    now,
    openGroups,
  });
  $('sources-reset').hidden = !state.prefs.hiddenSources.length;
  // Each term's hits in the current view (New, Unread...), filters and search, so a chip agrees with
  // the briefing summary beside it. In the Watchlist hits view that is every hit.
  const view = state.prefs.view === 'watchlist' ? 'all' : state.prefs.view;
  const pool = filterItems(itemsForView(view, saved), filterContext(view, state.tokens, { watchTerm: null }));
  const termCounts = new Map(state.terms.map((term) => [term, pool.filter((item) => item.watch.includes(term)).length]));
  const activeTerm = state.prefs.view === 'watchlist' ? state.watchTerm : null;
  ui.renderWatchTerms($('watch-terms'), state.terms, termCounts, activeTerm);
  ui.renderWatchUpgrades($('watch-upgrades'), termUpgrades(termCounts, pool), state.upgradesOpen);
  updateMarkAll();
  restoreFocus(focused);
}

function renderHeader() {
  const fresh = freshness();
  renderWatch(fresh);
  if (fresh) {
    // Written for readers: what they can rely on. The owner's fix lives in the watch report.
    const latest = (state.pending ?? state.data)?.generated_at;
    // Briefing views carry the stale state in their summary line instead of a banner.
    $('stale-banner').hidden = !fresh.stale || staleHiddenFor() === latest || BRIEFING_VIEWS.has(state.prefs.view);
    const message = fresh.stale
      ? `This feed was last ${fresh.label.toLowerCase()} (${momentLabel(fresh.generated)}). Newer reporting may be missing.`
      : '';
    const text = $('stale-text');
    if (text.textContent !== message) text.textContent = message; // a live region: only real changes
    // Phones: one line. The chip already says Stale; this says how old and what it means.
    // The chip beside the search already says how old the data is ("STALE 3d"): the phone banner
    // adds only what that means.
    $('stale-short').textContent = fresh.stale ? 'Newer reports may be missing.' : '';
  }
}

// Keep keyboard focus on the same sidebar control when the sidebar is rebuilt.
function focusKey(node) {
  if (!node?.dataset) return null;
  for (const attr of ['category', 'source', 'only', 'removeTerm', 'watchTerm']) {
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

function setView(view, { watchTerm = null } = {}) {
  state.prefs.view = VIEWS.includes(view) ? view : 'all';
  state.watchTerm = state.prefs.view === 'watchlist' ? watchTerm : null;
  state.showAllHits = false;
  savePrefs();
  renderAll();
  scrollToFeedTop();
  closeDrawer();
  const name = state.watchTerm ? `Watchlist hits for ${state.watchTerm}` : VIEW_LABELS[state.prefs.view];
  speak(`${name}: ${plural(visibleItems().length, 'item')}`);
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

/** Empty the search box and everything derived from it. */
function clearSearchState() {
  $('search').value = '';
  state.query = '';
  state.tokens = [];
  state.widened = null;
}

function resetFilters(event) {
  state.prefs.hiddenCategories = [];
  state.prefs.hiddenSources = [];
  state.prefs.view = 'all';
  state.watchTerm = null;
  clearSearchState();
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
function unreadVisibleIds(list = visibleItems()) {
  return list
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
  const hadFocus = document.activeElement?.matches?.('[data-mark-all], [data-feed-action="mark-view"]');
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
function updateMarkAll(list = state.data ? visibleItems() : []) {
  const count = unreadVisibleIds(list).length;
  for (const button of document.querySelectorAll('[data-mark-all]')) {
    button.disabled = count === 0;
    // "Nothing to mark", not "All read": an empty search or view has nothing unread *shown*,
    // which says nothing about the rest of the feed.
    // "Mark 12 read"; on half screens the " read" tail is hidden, leaving "Mark 12".
    const text = button.querySelector('.btn-label');
    if (count) text.replaceChildren(ui.el('span', 'mark-word', 'Mark '), ui.el('span', 'mark-count', String(count)), ui.el('span', 'mark-tail', ' read'));
    else text.textContent = 'Nothing to mark';
    const label = count
      ? `Mark all ${plural(count, 'unread item')} in this view as read`
      : 'Nothing unread in this view';
    button.setAttribute('aria-label', label);
    button.title = label;
  }
  refreshBriefing(list);
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

// ── Density ─────────────────────────────────────────────────────────────────
// Until the reader picks a density, every screen (phones included) starts comfortable.
function applyDefaultDensity() {
  if (DENSITIES.includes(state.prefs.density)) return;
  state.prefs.density = 'comfortable';
}

// Comfortable (headline, meta, two-line summary) is the default; compact is headlines and meta
// only, for a fast briefing scan or a second screen. A focused row shows its summary.
function syncDensity() {
  const compact = state.prefs.density === 'compact';
  $('feed').dataset.density = state.prefs.density;
  for (const button of document.querySelectorAll('[data-density-toggle]')) button.setAttribute('aria-pressed', String(compact));
  $('density-btn-drawer').textContent = 'Compact rows';
}

function toggleDensity() {
  state.prefs.density = state.prefs.density === 'compact' ? 'comfortable' : 'compact';
  savePrefs();
  syncDensity();
  speak(state.prefs.density === 'compact' ? 'Compact rows: headlines only' : 'Comfortable rows: with summaries');
}

// ── Drawer (phones and small tablets) ───────────────────────────────────────
// While closed, the off-screen sidebar is inert (not focusable or announced); while open it
// is modal: the rest of the page is inert until it closes.
const phone = window.matchMedia('(max-width: 600px)');
function syncSearchPlaceholder() {
  // Each width gets a placeholder that fits whole, instead of one cut off mid-word.
  $('search').placeholder = phone.matches ? 'Search' : midWidth.matches ? 'Search (press /)' : 'Search headlines and summaries (press /)';
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

// The button that opened the drawer (the top-bar menu, or Filters in the phone tab bar) gets focus back.
let drawerOpener = null;
const drawerButtons = () => [$('menu-btn'), $('tab-filters')];

function openDrawer(event) {
  drawerOpener = event?.currentTarget ?? null;
  document.body.classList.add('drawer-open');
  $('scrim').hidden = false;
  for (const button of drawerButtons()) button.setAttribute('aria-expanded', 'true');
  syncDrawer();
  $('sidebar-close').focus();
}

function closeDrawer({ returnFocus = true } = {}) {
  if (!document.body.classList.contains('drawer-open')) return;
  document.body.classList.remove('drawer-open');
  $('scrim').hidden = true;
  for (const button of drawerButtons()) button.setAttribute('aria-expanded', 'false');
  syncDrawer();
  if (returnFocus && narrow.matches) {
    const shown = (button) => button?.getClientRects().length > 0;
    const target = shown(drawerOpener) ? drawerOpener : drawerButtons().find(shown);
    target?.focus();
  }
  drawerOpener = null;
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

/**
 * Re-read prefs and the watchlist after a restore or another tab's change. With keepView, this
 * tab stays on the view it is showing; filters and density follow what was stored.
 */
function reloadFromStorage({ keepView = false } = {}) {
  const view = state.prefs.view;
  state.prefs = storage.prefs();
  applyDefaultDensity();
  if (keepView) state.prefs.view = view;
  if (!VIEWS.includes(state.prefs.view)) state.prefs.view = 'all';
  state.terms = storage.watchlist();
  recomputeWatch();
  syncDensity();
  renderAll();
}

async function importSettings(file) {
  try {
    const result = storage.importData(JSON.parse(await file.text()));
    reloadFromStorage();
    announce(`Restored: ${plural(result.saved, 'saved item')} and ${plural(result.terms, 'watchlist term')} added`);
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

/**
 * Set the search. Whole words first; when that finds nothing here and the prefix form does
 * ("ransom" → "ransom*"), run the prefix form and say so, unless the reader asked for exact.
 */
function setQuery(query) {
  state.query = query;
  state.tokens = parseQuery(query);
  state.widened = null;
  const trimmed = query.trim();
  if (!state.tokens.length || trimmed === state.exactQuery || visibleItems().length) return;
  const suggestion = prefixSuggestion(trimmed);
  if (!suggestion) return;
  const tokens = parseQuery(suggestion);
  if (!filterItems(itemsForView(state.prefs.view), filterContext(state.prefs.view, tokens)).length) return;
  state.tokens = tokens;
  state.widened = { from: trimmed, to: suggestion };
}

/** Search the prefix form of the query ("Zelensky*"), from an empty state or the filter bar hint. */
function applySuggestion() {
  $('search').value = state.suggestion;
  state.query = state.suggestion;
  state.tokens = parseQuery(state.query);
  state.widened = null;
  renderSidebar(); // counts follow the search
  renderFeed();
  scrollToFeedTop();
  focusFirstItem();
  speak(`${plural(visibleItems().length, 'item')} match`);
}

function wireEvents() {
  document.querySelector('.view-list').addEventListener('click', (event) => {
    const button = event.target.closest('[data-view]');
    if (button) setView(button.dataset.view);
  });

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
      setQuery(event.target.value);
      renderSidebar(); // counts follow the search
      renderFeed();
      scrollToFeedTop();
      if (state.widened) speak(`No whole-word matches. Showing ${plural(visibleItems().length, 'item')} for ${state.widened.to}`);
      else if (state.tokens.length) speak(`${plural(visibleItems().length, 'item')} match`);
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
    const added = normalizeTerm(term);
    const hits = state.items.filter((item) => item.watch.includes(added)).length;
    speak(`${added} added to your watchlist: ${plural(hits, 'hit')}`);
  });

  $('watch-upgrades').addEventListener('click', (event) => {
    if (event.target.closest('[data-upgrades-toggle]') != null) {
      state.upgradesOpen = !state.upgradesOpen;
      renderSidebar();
      $('watch-upgrades').querySelector('[data-upgrades-toggle]')?.focus();
      return;
    }
    const upgrade = event.target.closest('[data-upgrade-term]');
    if (!upgrade) return;
    // Replace the term with its prefix form, in place, and keep focus on the new chip.
    const { upgradeTerm: from, variant } = upgrade.dataset;
    if (state.watchTerm === from) state.watchTerm = variant;
    changeWatchlist((terms) => terms.map((t) => (t === from ? variant : t)));
    $('watch-terms').querySelector(`[data-watch-term="${CSS.escape(variant)}"]`)?.focus();
    speak(`${from} is now ${variant}`);
  });

  $('watch-terms').addEventListener('click', (event) => {
    const filterTerm = event.target.closest('[data-watch-term]')?.dataset.watchTerm;
    if (filterTerm != null) {
      // A chip is a filter: its hits alone, or (pressed again) all hits.
      const active = state.prefs.view === 'watchlist' && state.watchTerm === filterTerm;
      setView('watchlist', { watchTerm: active ? null : filterTerm });
      return;
    }
    const term = event.target.closest('[data-remove-term]')?.dataset.removeTerm;
    if (term == null) return;
    if (state.watchTerm === term) state.watchTerm = null;
    const index = state.terms.indexOf(term);
    changeWatchlist((terms) => removeTerm(terms, term));
    $('watch-input').focus(); // the chip (and its button) no longer exists
    announce(`Removed ${term} from your watchlist`, {
      label: 'Undo',
      run() {
        changeWatchlist((terms) => {
          if (terms.some((t) => t.toLowerCase() === term.toLowerCase())) return terms;
          const next = [...terms];
          next.splice(Math.min(index, next.length), 0, term); // back in its old place
          return next;
        });
        announce(`${term} is back on your watchlist`);
      },
    });
  });

  const feed = $('feed');
  feed.addEventListener('click', (event) => {
    const feedAction = event.target.closest('[data-feed-action]')?.dataset.feedAction;
    if (feedAction === 'mark-view') {
      markAllRead();
      return;
    }
    if (feedAction === 'briefing-hits') {
      // Stay in the briefing: open the pinned hits in full and go to them.
      state.showAllHits = true;
      renderFeed();
      const pinned = $('feed').querySelector('.day-pinned');
      pinned?.scrollIntoView({ block: 'start' });
      pinned?.querySelector('.item-title a')?.focus({ preventScroll: true });
      speak(`All ${plural(pinned?.querySelectorAll('article').length ?? 0, 'watchlist hit')} in this briefing`);
      return;
    }
    if (feedAction === 'briefing-category') {
      const only = event.target.closest('[data-only-category]').dataset.onlyCategory;
      state.prefs.hiddenCategories = state.categories.filter((c) => c !== only);
      filtersChanged();
      focusFirstItem();
      speak(`${only} only: ${plural(visibleItems().length, 'item')}`);
      return;
    }
    if (feedAction === 'toggle-hits') {
      state.showAllHits = !state.showAllHits;
      renderFeed();
      $('feed').querySelector('[data-feed-action="toggle-hits"]')?.focus({ preventScroll: true });
      return;
    }
    const emptyAction = event.target.closest('[data-empty-action]')?.dataset.emptyAction;
    if (emptyAction === 'suggest' && state.suggestion) {
      applySuggestion();
      return;
    }
    if (emptyAction === 'search-all') {
      setView('all');
      $('search').focus({ preventScroll: true });
      return;
    }
    if (emptyAction?.startsWith('lift-')) {
      clearFilter(emptyAction.slice(5), event);
      return;
    }
    if (emptyAction === 'clear-search') {
      clearFilter('search', event);
      return;
    }
    if (emptyAction === 'all-hits') {
      setView('watchlist');
      focusFirstItem();
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
    const token = event.target.closest('[data-clear-filter]')?.dataset.clearFilter;
    const emptyAction = event.target.closest('[data-empty-action]')?.dataset.emptyAction;
    if (token) clearFilter(token, event);
    else if (emptyAction === 'suggest' && state.suggestion) applySuggestion();
    else if (emptyAction === 'show-saved') {
      state.prefs.hiddenCategories = [];
      clearFilter('sources', event);
    }
    else if (emptyAction === 'exact' && state.widened) {
      state.exactQuery = state.widened.from;
      setQuery(state.query);
      renderSidebar();
      renderFeed();
      $('search').focus({ preventScroll: true });
      speak(`Exact whole words: ${plural(visibleItems().length, 'item')}`);
    }
    else if (emptyAction) resetFilters(event);
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
  for (const [type, ms] of [['pointerenter', null], ['focusin', null], ['pointerleave', TOAST_MS], ['focusout', TOAST_MS]]) {
    $('status').addEventListener(type, () => {
      if (ms === null) clearTimeout(announceTimer);
      else if (!$('status').hidden) scheduleToastHide(ms);
    });
  }
  for (const button of document.querySelectorAll('[data-theme-toggle]')) button.addEventListener('click', toggleTheme);
  for (const button of document.querySelectorAll('[data-density-toggle]')) button.addEventListener('click', toggleDensity);
  $('watch-btn').addEventListener('click', () => setWatchPanel($('watch-panel').hidden));
  document.addEventListener('click', (event) => {
    if (!$('watch-panel').hidden && !event.target.closest('#watch')) setWatchPanel(false);
  });
  $('new-pill').addEventListener('click', () => {
    applyPending();
    focusFirstItem(); // the pill hides itself; continue from the newest item
  });
  $('menu-btn').addEventListener('click', openDrawer);
  $('tab-filters').addEventListener('click', openDrawer);
  $('tabbar').addEventListener('click', (event) => {
    const button = event.target.closest('[data-tab]');
    if (button) setView(button.dataset.tab);
  });
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
  $('skip-search').addEventListener('click', (event) => {
    event.preventDefault();
    $('search').focus();
  });
  $('help-btn').addEventListener('click', openHelp);
  $('labels-btn').addEventListener('click', openHelp);
  $('help-close').addEventListener('click', () => $('help').close());
  $('help').addEventListener('click', (event) => {
    if (event.target === $('help')) $('help').close(); // a click on the backdrop
  });

  document.addEventListener('keydown', (event) => {
    // Checkboxes and radios take no typing, so shortcuts keep working after one is ticked.
    const typing = event.target.closest?.('input:not([type="checkbox"], [type="radio"]), textarea, select, [contenteditable="true"]');
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
        clearSearchState();
        renderSidebar(); // counts follow the search
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

  // Read/saved/watchlist/prefs changes made in another tab. Prefs are re-read so this tab's next
  // save cannot write its stale copy over them.
  storage.listen((key) => {
    if (!state.data) return;
    if (key === 'prefs') reloadFromStorage({ keepView: true });
    else if (key === null || key === 'watchlist') {
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
  if (key === 'd') {
    toggleDensity();
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
syncDensity();
syncDrawer();
// Name the modifier Mac users actually press (Cmd+Z works everywhere it says Ctrl+Z).
if (/Mac|iPhone|iPad/.test(navigator.userAgentData?.platform ?? navigator.platform ?? '')) $('undo-mod').textContent = '⌘';
syncSearchPlaceholder();
phone.addEventListener('change', () => {
  syncSearchPlaceholder();
  if (state.data) renderAll(); // the view token appears or goes with the tab bar
});
midWidth.addEventListener('change', syncSearchPlaceholder);
wireEvents();
loadInitial();
setInterval(tick, TICK_MS);
// Tells js/boot-check.js the app is up, so it never replaces the page with its failure message.
document.documentElement.dataset.app = 'ready';
