import assert from 'node:assert/strict';
import { test } from 'node:test';

import { filterItems, fold, matchesQuery, parseQuery, sortItems } from '../../site/js/filters.js';

function item(id, overrides = {}) {
  const base = { id, source: 'alpha', category: 'Cyber', title: id, summary: '', watch: [], publishedMs: 0, firstSeenMs: 0 };
  const merged = { ...base, ...overrides };
  return { ...merged, searchText: fold(`${merged.title} ${merged.summary} ${merged.source}`) };
}

const ITEMS = [
  item('ransom', { title: 'Ransomware hits hospital', watch: ['ransomware'] }),
  item('geo', { source: 'bravo', category: 'Geopolitics', title: 'Ceasefire talks in Kyiv' }),
  item('cafe', { title: 'Café chain breached', summary: 'Card data stolen' }),
];

function ctx(overrides = {}) {
  return {
    view: 'all',
    tokens: [],
    hiddenCategories: new Set(),
    hiddenSources: new Set(),
    isRead: () => false,
    isSaved: () => false,
    isNew: () => false,
    ...overrides,
  };
}

const ids = (list) => list.map((i) => i.id);

test('fold strips accents and case', () => {
  assert.equal(fold('Café ZELENSKYY'), 'cafe zelenskyy');
});

test('parseQuery keeps quoted phrases', () => {
  assert.deepEqual(parseQuery('  "Volt Typhoon"  cisa '), ['volt typhoon', 'cisa']);
  assert.deepEqual(parseQuery(''), []);
  assert.ok(matchesQuery('a volt typhoon b cisa', parseQuery('cisa "volt typhoon"')));
  assert.ok(!matchesQuery('volt b typhoon', parseQuery('"volt typhoon"')));
});

test('search requires every token', () => {
  assert.deepEqual(ids(filterItems(ITEMS, ctx({ tokens: parseQuery('cafe card') }))), ['cafe']);
  assert.deepEqual(ids(filterItems(ITEMS, ctx({ tokens: parseQuery('cafe kyiv') }))), []);
});

test('category and source filters', () => {
  assert.deepEqual(ids(filterItems(ITEMS, ctx({ hiddenCategories: new Set(['Cyber']) }))), ['geo']);
  assert.deepEqual(ids(filterItems(ITEMS, ctx({ hiddenSources: new Set(['alpha']) }))), ['geo']);
});

test('views', () => {
  assert.deepEqual(ids(filterItems(ITEMS, ctx({ view: 'unread', isRead: (id) => id === 'geo' }))), ['ransom', 'cafe']);
  assert.deepEqual(ids(filterItems(ITEMS, ctx({ view: 'saved', isSaved: (id) => id === 'cafe' }))), ['cafe']);
  assert.deepEqual(ids(filterItems(ITEMS, ctx({ view: 'watchlist' }))), ['ransom']);
  assert.deepEqual(ids(filterItems(ITEMS, ctx({ view: 'new', isNew: (i) => i.id === 'geo' }))), ['geo']);
});

test('sortItems is newest first, then most recently seen', () => {
  const list = [
    item('old', { publishedMs: 1, firstSeenMs: 5 }),
    item('newest', { publishedMs: 3, firstSeenMs: 3 }),
    item('tie-later', { publishedMs: 2, firstSeenMs: 9 }),
    item('tie-earlier', { publishedMs: 2, firstSeenMs: 4 }),
  ];
  assert.deepEqual(ids(sortItems(list)), ['newest', 'tie-later', 'tie-earlier', 'old']);
});
