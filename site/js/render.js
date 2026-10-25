// DOM building. All feed text goes through textContent / text nodes, never innerHTML.

import { highlightSegments, queryRanges } from './filters.js';
import { clockTime, dayKey, dayLabel, fullTime, relativeTime, updatedLabel } from './time.js';

const SVG_NS = 'http://www.w3.org/2000/svg';
const ICON_PATHS = {
  star: 'M12 3.8l2.5 5.1 5.6.8-4 3.9.9 5.6L12 16.6l-5 2.6.9-5.6-4-3.9 5.6-.8z',
  check: 'M5 12.5l4.5 4.5L19 7.5',
  // Read toggle: an empty ring while unread; the check inside appears once read (see CSS).
  ring: 'M12 4.25a7.75 7.75 0 1 0 0 15.5 7.75 7.75 0 0 0 0-15.5z',
  tick: 'M8.4 12.3l2.5 2.5 4.8-5.1',
  close: 'M6 6l12 12M18 6L6 18',
  eye: 'M2.5 12s3.5-6.5 9.5-6.5 9.5 6.5 9.5 6.5-3.5 6.5-9.5 6.5S2.5 12 2.5 12zM12 9.25a2.75 2.75 0 1 0 0 5.5 2.75 2.75 0 0 0 0-5.5z',
};

export function icon(name, ...extra) {
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('class', `icon icon-${name}`);
  for (const part of [name, ...extra]) {
    const path = document.createElementNS(SVG_NS, 'path');
    path.setAttribute('d', ICON_PATHS[part]);
    path.setAttribute('class', `path-${part}`);
    svg.append(path);
  }
  return svg;
}

export function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

/** Only http(s) links are ever rendered. */
export function safeUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.href : null;
  } catch {
    return null;
  }
}

export function slug(text) {
  return String(text ?? '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'other';
}

/** Watchlist terms and search matches, layered: each gets its own <mark> style. */
export function appendHighlighted(parent, text, { matcher, tokens } = {}) {
  if (!matcher && !tokens?.length) {
    parent.append(text);
    return;
  }
  const layers = { watch: matcher ? matcher.ranges(text) : [], search: queryRanges(text, tokens) };
  for (const segment of highlightSegments(text, layers)) {
    if (!segment.kinds.length) {
      parent.append(segment.text);
      continue;
    }
    const mark = el('mark', segment.kinds.map((kind) => `hl-${kind}`).join(' '), segment.text);
    parent.append(mark);
  }
}

function separator() {
  return el('span', 'sep', '·');
}

/**
 * Toggle buttons keep one name; aria-pressed carries the state. (Changing the name as well makes
 * screen readers announce the state twice: "Remove from saved, pressed".) The tooltip says what a
 * click will do.
 */
export function setActionState(button, pressed) {
  const kind = button.dataset.action;
  button.setAttribute('aria-pressed', String(pressed));
  button.setAttribute('aria-label', kind === 'save' ? 'Save for later' : 'Mark as read');
  button.title =
    kind === 'save' ? (pressed ? 'Saved: click to remove' : 'Save for later') : pressed ? 'Read: click to mark unread' : 'Mark as read';
}

function actionButton(kind, pressed) {
  const button = el('button', `item-btn btn-${kind}`);
  button.type = 'button';
  button.dataset.action = kind;
  button.append(kind === 'save' ? icon('star') : icon('ring', 'tick'));
  setActionState(button, pressed);
  return button;
}

// Roughly what two clamped summary lines show; a first match past this would be cut off.
const VISIBLE_CHARS = 110;

/**
 * Where to start the summary so the reason a row is here stays visible: the search match (or, in
 * the Watchlist hits view, the watch match) when the headline has none and the summary's first one
 * falls past the visible lines. Starts a few words before it, at a word boundary.
 */
function matchWindow(item, ctx) {
  const none = { start: 0 };
  const searching = ctx.tokens?.length > 0;
  const watching = ctx.view === 'watchlist' && ctx.matcher;
  if (!searching && !watching) return none;
  const ranges = (text) => (searching ? queryRanges(text, ctx.tokens) : ctx.matcher.ranges(text));
  if (ranges(item.title).length) return none;
  const first = ranges(item.summary)[0];
  if (!first || first[0] < VISIBLE_CHARS) return none;
  const space = item.summary.lastIndexOf(' ', first[0] - 40);
  return { start: space > 0 ? space + 1 : 0 };
}

/** ctx: { now, view, matcher, tokens, isRead(id), isSaved(id), isNew(item), isArrived(item) } */
export function itemElement(item, ctx) {
  const article = el('article', 'item');
  article.dataset.id = item.id;
  const isNew = ctx.isNew(item);
  article.classList.toggle('is-read', ctx.isRead(item.id));
  article.classList.toggle('is-watch', item.watch.length > 0);

  const body = el('div', 'item-body');
  const heading = el('h3', 'item-title');
  const href = safeUrl(item.url);
  let target;
  if (href) {
    target = el('a');
    target.href = href;
    target.target = '_blank';
    target.rel = 'noopener noreferrer';
    target.setAttribute('aria-describedby', 'new-tab-hint');
  } else {
    target = el('span');
  }
  target.dir = 'auto'; // an Arabic or Hebrew headline gets its own direction
  appendHighlighted(target, item.title, ctx);
  heading.append(target);

  const meta = el('div', 'item-meta');
  const source = el('span', `item-source cat-${slug(item.category)}`, item.sourceName);
  source.title = [item.category, item.group].filter(Boolean).join(' › ');
  const time = el('time', 'item-time', `${item.dateEstimated ? '~' : ''}${clockTime(item.publishedMs)}`);
  time.dateTime = new Date(item.publishedMs).toISOString();
  time.title = item.dateEstimated
    ? `${fullTime(item.publishedMs)}: the source gave no publication time, so this is when Owlfeed first saw it`
    : fullTime(item.publishedMs);
  const age = el('span', 'item-age', relativeTime(item.publishedMs, ctx.now));
  age.dataset.ms = String(item.publishedMs);
  // Each separator ends the part before it, so a wrapped line never starts with "·".
  const part = (...nodes) => {
    const span = el('span', 'meta-part');
    span.append(...nodes);
    return span;
  };
  meta.append(part(source, separator()), part(time, separator()), age);
  // "Just in" (landed while the page was open) outranks NEW. Both drop once the row is read (CSS).
  if (ctx.isArrived?.(item)) {
    const badge = el('span', 'badge badge-new badge-arrived', 'Just in');
    badge.title = 'Arrived while this page was open';
    meta.append(badge);
  } else if (isNew) meta.append(el('span', 'badge badge-new', 'New'));
  for (const term of item.watch) {
    const badge = el('span', 'badge badge-watch');
    badge.title = `Matches your watchlist term “${term}”`;
    badge.append(icon('eye'), el('span', 'sr-only', 'Watchlist: '), el('bdi', null, term));
    meta.append(badge);
  }

  body.append(heading, meta);
  if (item.summary) {
    const summary = el('p', 'item-summary');
    summary.dir = 'auto';
    const { start } = matchWindow(item, ctx);
    if (start > 0) {
      // The match that put this row here sits past the two visible lines: start the summary near it.
      summary.classList.add('is-snippet');
      summary.append('…');
    }
    appendHighlighted(summary, item.summary.slice(start), ctx);
    body.append(summary);
  } else {
    body.append(el('p', 'item-summary is-empty', 'No summary provided by the source.'));
  }

  const actions = el('div', 'item-actions');
  actions.append(actionButton('save', ctx.isSaved(item.id)), actionButton('read', ctx.isRead(item.id)));
  article.append(body, actions);
  return article;
}

/**
 * Renders a long list in pages as the reader scrolls, grouped under day headers.
 * Uses IntersectionObserver only (no timers), so it behaves the same under a fake clock.
 */
export function createFeedRenderer(container, sentinel, pageSize = 80) {
  let entries = [];
  let ctx = null;
  let index = 0;
  let lastDay = null;
  let currentList = null;
  let endNote = null;

  const observer = new IntersectionObserver(
    (records) => {
      if (records.some((record) => record.isIntersecting)) renderMore();
    },
    { rootMargin: '1200px 0px' },
  );

  function recheck() {
    // Re-observing delivers a fresh notification, so a sentinel that is still on screen loads the next page.
    observer.unobserve(sentinel);
    if (index < entries.length) observer.observe(sentinel);
  }

  function section(title, detail, className = 'day') {
    const node = el('section', className);
    const header = el('h2', 'day-header');
    header.append(el('span', 'day-title', title), el('span', 'day-detail', detail));
    currentList = el('div', 'day-items');
    node.append(header, currentList);
    return node;
  }

  function renderMore() {
    if (!ctx) return;
    const end = Math.min(entries.length, index + pageSize);
    const fragment = document.createDocumentFragment();
    for (; index < end; index += 1) {
      const item = entries[index];
      const day = Math.min(item.publishedMs, ctx.now); // slightly future items group under today
      const key = dayKey(day);
      if (key !== lastDay) {
        const label = dayLabel(day, ctx.now);
        fragment.append(section(label.title, label.detail));
        lastDay = key;
      }
      currentList.append(itemElement(item, ctx));
    }
    // The finish line, once the last page is on screen.
    if (index >= entries.length && endNote) {
      if (typeof endNote === 'function') endNote = endNote();
      if (endNote) fragment.append(endNote);
      endNote = null;
    }
    container.append(fragment);
    sentinel.hidden = index >= entries.length;
    recheck();
  }

  return {
    /**
     * options.pinned: items shown first under their own header (watchlist hits in a briefing),
     * with pinnedDetail beside the header and pinnedFooter (a Show all toggle) after them;
     * options.lead: a node above everything (the briefing summary); options.end: a node after the
     * last item (the caught-up marker), or a function that builds it when it is appended; options.minCount: draw at least this many rows at once, so
     * redrawing a list the reader had scrolled down keeps their place and focus.
     */
    render(list, context, { pinned = [], pinnedDetail = '', pinnedFooter = null, lead = null, end = null, minCount = 0 } = {}) {
      entries = list;
      ctx = context;
      index = 0;
      lastDay = null;
      currentList = null;
      endNote = end;
      container.replaceChildren();
      if (lead) container.append(lead);
      if (pinned.length) {
        const hits = section('Watchlist hits', pinnedDetail, 'day day-pinned');
        for (const item of pinned) currentList.append(itemElement(item, ctx));
        if (pinnedFooter) hits.append(pinnedFooter);
        container.append(hits);
      }
      do renderMore();
      while (ctx && index < Math.min(minCount, entries.length));
    },
    get size() {
      return entries.length;
    },
    /** How many rows of the list are on the page. */
    get rendered() {
      return index;
    },
  };
}

export function emptyState(title, detail, action) {
  const box = el('div', 'empty');
  box.append(el('p', 'empty-title', title));
  if (detail) box.append(el('p', 'empty-detail', detail));
  if (action) {
    const button = el('button', 'btn', action.label);
    button.type = 'button';
    button.dataset.emptyAction = action.id;
    box.append(button);
  }
  return box;
}

/** Refresh every "12m ago" label in place. */
export function refreshAges(root, now) {
  for (const node of root.querySelectorAll('.item-age[data-ms]')) {
    node.textContent = relativeTime(Number(node.dataset.ms), now);
  }
}

function checkRow({ attr, value, checked, label, count, dotClass, dotTitle, dotText }) {
  const row = el('label', 'check-row');
  const input = el('input');
  input.type = 'checkbox';
  input.dataset[attr] = value;
  input.checked = checked;
  const dot = el('span', dotClass);
  if (dotTitle) dot.title = dotTitle; // a mouse tooltip only; dotText says it for screen readers
  if (dotText) dot.setAttribute('aria-hidden', 'true');
  const name = el('span', 'row-label', label);
  // The dot's meaning in words, for screen readers (a title alone is never announced reliably).
  if (dotText) name.append(el('span', 'sr-only', `, ${dotText}`));
  row.append(input, dot, name, el('span', 'count', String(count)));
  return row;
}

/**
 * Category checkboxes agree with the source filters: checked when all of a category's sources are
 * shown, mixed (indeterminate) when only some are, empty when none are or the category is hidden.
 * The count is what that category shows now. sourceState: Map(category -> { shown, total }).
 */
export function renderCategories(list, categories, hidden, counts, sourceState = new Map(), allCounts = counts) {
  list.replaceChildren(
    ...categories.map((category) => {
      const li = el('li');
      const { shown = 1, total = 1 } = sourceState.get(category) ?? {};
      const visible = !hidden.has(category) && shown > 0;
      const row = checkRow({
        attr: 'category',
        value: category,
        checked: visible && shown === total,
        label: category,
        // Hidden (by its checkbox or all its sources): what showing it would add, never a misleading 0.
        count: (visible ? counts : allCounts).get(category) ?? 0,
        dotClass: `cat-dot cat-${slug(category)}`,
      });
      const input = row.querySelector('input');
      if (!visible) {
        const count = row.querySelector('.count');
        count.classList.add('is-hidden');
        count.append(el('span', 'sr-only', ' hidden'));
        count.title = `${count.firstChild.textContent} hidden by this filter`;
      }
      input.indeterminate = visible && shown < total;
      if (input.indeterminate) row.title = `${shown} of ${total} ${category} sources shown`;
      li.append(row);
      return li;
    }),
  );
}

export function healthTitle(source, now) {
  if (source.status === 'ok') return 'Fetched successfully on the last refresh';
  const last = Date.parse(source.last_ok);
  const since = Number.isFinite(last) ? ` Last success ${updatedLabel(last, now)}.` : ' No successful fetch yet.';
  return `Last refresh failed: ${source.error || 'unknown error'}.${since}`;
}

/**
 * Sources grouped under collapsible headings. openGroups holds the groups the reader opened; a
 * group with a failing source or a partial selection opens by itself, unless the reader closed
 * it (closedGroups).
 */
export function renderSources(container, sources, { hiddenSources, hiddenCategories, counts, now, openGroups, closedGroups = new Set(), staleSince = null }) {
  const groups = new Map();
  for (const source of sources) {
    const key = `${source.category} › ${source.group}`;
    if (!groups.has(key)) groups.set(key, { category: source.category, title: key, sources: [] });
    groups.get(key).sources.push(source);
  }
  const nodes = [];
  for (const group of groups.values()) {
    const wrapper = el('details', 'source-group');
    wrapper.dataset.group = group.title;
    const categoryHidden = hiddenCategories.has(group.category);
    wrapper.classList.toggle('is-muted', categoryHidden);
    // A hidden category shows none of its sources, whatever their own checkboxes say.
    const shown = categoryHidden ? 0 : group.sources.filter((s) => !hiddenSources.has(s.id)).length;
    const failing = group.sources.filter((s) => s.status !== 'ok').length;
    // Open what needs a look: a failing source, or a partial selection. A group that is all on or
    // all off says everything in its tally ("10/10", "0/7"), so it stays folded.
    const partial = shown > 0 && shown < group.sources.length;
    // One the reader closed stays closed, even while it has something to show.
    wrapper.open = openGroups.has(group.title) || (!closedGroups.has(group.title) && (failing > 0 || partial));
    const summary = el('summary', 'group-heading');
    summary.dataset.groupSummary = group.title; // lets focus come back here after a redraw
    summary.append(el('span', 'group-title', group.title));
    const tally = el('span', `group-tally${failing ? ' is-error' : ''}`, `${shown}/${group.sources.length}`);
    tally.title = `${shown} of ${group.sources.length} sources shown${failing ? `, ${failing} not answering` : ''}`;
    summary.append(tally);
    wrapper.append(summary);
    const list = el('ul', 'source-list');
    for (const source of group.sources) {
      const li = el('li', 'source-row');
      li.classList.toggle('is-error', source.status !== 'ok');
      // Stale data: a source that answered at the last sweep may not answer now. Unknown, not healthy.
      const unknown = staleSince != null && source.status === 'ok';
      const unknownText = unknown ? `Answered at the last sweep, ${updatedLabel(staleSince, now)}. No refresh since, so its state now is unknown` : '';
      li.append(
        checkRow({
          attr: 'source',
          value: source.id,
          checked: !hiddenSources.has(source.id),
          label: source.name,
          count: counts.get(source.id) ?? 0,
          dotClass: `health-dot ${unknown ? 'is-unknown' : source.status === 'ok' ? 'is-ok' : 'is-error'}`,
          dotTitle: unknown ? unknownText : healthTitle(source, now),
          dotText: unknown ? `state unknown: ${unknownText}` : source.status === 'ok' ? 'answering' : `not answering: ${healthTitle(source, now)}`,
        }),
      );
      const only = el('button', 'only-btn', 'only');
      only.type = 'button';
      only.dataset.only = source.id;
      only.setAttribute('aria-label', `Show only ${source.name}`);
      li.append(only);
      list.append(li);
    }
    wrapper.append(list);
    nodes.push(wrapper);
  }
  container.replaceChildren(...nodes);
}

/**
 * Terms whose prefix form would catch more, gathered into one quiet line under the chips
 * ("2 terms could catch more · Review"); Review lists each offer: "Zelensky → Zelensky* (+3)".
 */
export function renderWatchUpgrades(box, upgrades, open) {
  box.replaceChildren();
  box.hidden = upgrades.size === 0;
  if (!upgrades.size) return;
  const line = el('p', 'watch-upgrades-line', `${upgrades.size === 1 ? '1 term' : `${upgrades.size} terms`} could catch more. `);
  const toggle = el('button', 'link-btn', open ? 'Hide' : 'Review');
  toggle.type = 'button';
  toggle.dataset.upgradesToggle = '';
  toggle.setAttribute('aria-expanded', String(open));
  line.append(toggle);
  box.append(line);
  if (!open) return;
  const list = el('ul', 'watch-upgrades-list');
  for (const [term, { variant, extra }] of upgrades) {
    const li = el('li');
    const offer = el('button', 'watch-upgrade');
    offer.type = 'button';
    offer.dataset.upgradeTerm = term;
    offer.dataset.variant = variant;
    offer.setAttribute('aria-label', `Change ${term} to ${variant} to catch ${extra} more`);
    offer.append(`${term} → ${variant} `, el('span', 'watch-upgrade-extra', `+${extra}`));
    li.append(offer);
    list.append(li);
  }
  box.append(list, el('p', 'hint', 'A trailing * also matches longer words, such as other spellings.'));
}

/**
 * Watchlist chips. Each is a filter: pressing it shows that term's hits alone (pressed again, all
 * hits), with its hit count under the current category and source filters. The × removes the term.
 */
export function renderWatchTerms(list, terms, counts = new Map(), active = null) {
  list.replaceChildren(
    ...terms.map((term) => {
      const li = el('li', 'chip');
      const count = counts.get(term) ?? 0;
      const pressed = term === active;
      li.classList.toggle('is-active', pressed);
      li.classList.toggle('is-quiet', count === 0);
      const filter = el('button', 'chip-filter');
      filter.type = 'button';
      filter.dataset.watchTerm = term;
      filter.setAttribute('aria-pressed', String(pressed));
      filter.setAttribute('aria-label', `${term}: ${count === 1 ? '1 hit' : `${count} hits`}`);
      filter.title = pressed ? 'Showing only these hits: click to show all watchlist hits' : `Show only hits for ${term}`;
      filter.append(el('span', 'chip-label', term), el('span', 'chip-count', String(count)));
      const remove = el('button', 'chip-remove');
      remove.type = 'button';
      remove.dataset.removeTerm = term;
      remove.setAttribute('aria-label', `Remove ${term} from watchlist`);
      remove.append(icon('close'));
      li.append(filter, remove);
      return li;
    }),
  );
}
