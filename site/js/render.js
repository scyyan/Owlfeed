// DOM building. All feed text goes through textContent / text nodes, never innerHTML.

import { clockTime, dayKey, dayLabel, fullTime, relativeTime, updatedLabel } from './time.js';

const SVG_NS = 'http://www.w3.org/2000/svg';
const ICON_PATHS = {
  star: 'M12 3.8l2.5 5.1 5.6.8-4 3.9.9 5.6L12 16.6l-5 2.6.9-5.6-4-3.9 5.6-.8z',
  check: 'M5 12.5l4.5 4.5L19 7.5',
  close: 'M6 6l12 12M18 6L6 18',
};

export function icon(name) {
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('class', `icon icon-${name}`);
  const path = document.createElementNS(SVG_NS, 'path');
  path.setAttribute('d', ICON_PATHS[name]);
  svg.append(path);
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

export function appendHighlighted(parent, text, matcher) {
  if (!matcher) {
    parent.append(text);
    return;
  }
  for (const part of matcher.parts(text)) {
    parent.append(part.match ? el('mark', null, part.text) : part.text);
  }
}

function separator() {
  return el('span', 'sep', '·');
}

export function setActionState(button, pressed) {
  const kind = button.dataset.action;
  const label =
    kind === 'save' ? (pressed ? 'Remove from saved' : 'Save for later') : pressed ? 'Mark as unread' : 'Mark as read';
  button.setAttribute('aria-pressed', String(pressed));
  button.setAttribute('aria-label', label);
  button.title = label;
}

function actionButton(kind, pressed) {
  const button = el('button', `item-btn btn-${kind}`);
  button.type = 'button';
  button.dataset.action = kind;
  button.append(icon(kind === 'save' ? 'star' : 'check'));
  setActionState(button, pressed);
  return button;
}

/** ctx: { now, matcher, isRead(id), isSaved(id), isNew(item) } */
export function itemElement(item, ctx) {
  const article = el('article', 'item');
  article.dataset.id = item.id;
  const isNew = ctx.isNew(item);
  article.classList.toggle('is-read', ctx.isRead(item.id));
  article.classList.toggle('is-new', isNew);
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
  } else {
    target = el('span');
  }
  appendHighlighted(target, item.title, ctx.matcher);
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
  meta.append(source, separator(), time, separator(), age);
  if (isNew) meta.append(el('span', 'badge badge-new', 'New'));
  for (const term of item.watch) meta.append(el('span', 'badge badge-watch', term));

  body.append(heading, meta);
  if (item.summary) {
    const summary = el('p', 'item-summary');
    appendHighlighted(summary, item.summary, ctx.matcher);
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

  function renderMore() {
    if (!ctx || index >= entries.length) return;
    const end = Math.min(entries.length, index + pageSize);
    const fragment = document.createDocumentFragment();
    for (; index < end; index += 1) {
      const item = entries[index];
      const key = dayKey(item.publishedMs);
      if (key !== lastDay) {
        const section = el('section', 'day');
        const label = dayLabel(item.publishedMs, ctx.now);
        const header = el('h2', 'day-header');
        header.append(el('span', 'day-title', label.title), el('span', 'day-detail', label.detail));
        currentList = el('div', 'day-items');
        section.append(header, currentList);
        fragment.append(section);
        lastDay = key;
      }
      currentList.append(itemElement(item, ctx));
    }
    container.append(fragment);
    sentinel.hidden = index >= entries.length;
    recheck();
  }

  return {
    render(list, context) {
      entries = list;
      ctx = context;
      index = 0;
      lastDay = null;
      currentList = null;
      container.replaceChildren();
      renderMore();
    },
    get size() {
      return entries.length;
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

function checkRow({ attr, value, checked, label, count, dotClass, dotTitle }) {
  const row = el('label', 'check-row');
  const input = el('input');
  input.type = 'checkbox';
  input.dataset[attr] = value;
  input.checked = checked;
  const dot = el('span', dotClass);
  if (dotTitle) dot.title = dotTitle;
  row.append(input, dot, el('span', 'row-label', label), el('span', 'count', String(count)));
  return row;
}

export function renderCategories(list, categories, hidden, counts) {
  list.replaceChildren(
    ...categories.map((category) => {
      const li = el('li');
      li.append(
        checkRow({
          attr: 'category',
          value: category,
          checked: !hidden.has(category),
          label: category,
          count: counts.get(category) ?? 0,
          dotClass: `cat-dot cat-${slug(category)}`,
        }),
      );
      return li;
    }),
  );
}

function healthTitle(source, now) {
  if (source.status === 'ok') return 'Fetched successfully on the last refresh';
  const last = Date.parse(source.last_ok);
  const since = Number.isFinite(last) ? ` Last success ${updatedLabel(last, now)}.` : ' No successful fetch yet.';
  return `Last refresh failed: ${source.error || 'unknown error'}.${since}`;
}

export function renderSources(container, sources, { hiddenSources, hiddenCategories, counts, now }) {
  const groups = new Map();
  for (const source of sources) {
    const key = `${source.category} › ${source.group}`;
    if (!groups.has(key)) groups.set(key, { category: source.category, title: key, sources: [] });
    groups.get(key).sources.push(source);
  }
  const nodes = [];
  for (const group of groups.values()) {
    const wrapper = el('div', 'source-group');
    wrapper.classList.toggle('is-muted', hiddenCategories.has(group.category));
    wrapper.append(el('h3', 'group-heading', group.title));
    const list = el('ul', 'source-list');
    for (const source of group.sources) {
      const li = el('li', 'source-row');
      li.classList.toggle('is-error', source.status !== 'ok');
      li.append(
        checkRow({
          attr: 'source',
          value: source.id,
          checked: !hiddenSources.has(source.id),
          label: source.name,
          count: counts.get(source.id) ?? 0,
          dotClass: `health-dot ${source.status === 'ok' ? 'is-ok' : 'is-error'}`,
          dotTitle: healthTitle(source, now),
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

export function renderWatchTerms(list, terms) {
  list.replaceChildren(
    ...terms.map((term) => {
      const li = el('li', 'chip');
      li.append(el('span', 'chip-label', term));
      const remove = el('button', 'chip-remove');
      remove.type = 'button';
      remove.dataset.removeTerm = term;
      remove.setAttribute('aria-label', `Remove ${term} from watchlist`);
      remove.append(icon('close'));
      li.append(remove);
      return li;
    }),
  );
}

export function renderHealth(container, sources, now) {
  const failing = sources.filter((s) => s.status !== 'ok');
  const summary = el('p', 'health-summary');
  summary.append(
    el('span', `health-dot ${failing.length ? 'is-error' : 'is-ok'}`),
    `${sources.length - failing.length} of ${sources.length} sources OK`,
  );
  const nodes = [summary];
  if (failing.length) {
    const details = el('details', 'health-details');
    details.append(el('summary', null, `${failing.length} failing`));
    const list = el('ul');
    for (const source of failing) {
      const li = el('li');
      li.append(el('strong', null, source.name), ` ${healthTitle(source, now)}`);
      list.append(li);
    }
    details.append(list);
    nodes.push(details);
  }
  container.replaceChildren(...nodes);
}
