import assert from 'node:assert/strict';
import { test } from 'node:test';

import { filterItems, fold, highlightSegments, matchesQuery, parseQuery, prefixSuggestion, queryRanges, sortItems } from '../../site/js/filters.js';

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

test('queryRanges finds folded tokens in the original text', () => {
  const text = 'Café chain breached; CAFE owners warned';
  assert.deepEqual(queryRanges(text, parseQuery('cafe')), [
    [0, 4],
    [21, 25],
  ]);
  assert.deepEqual(queryRanges('Volt Typhoon and volt', parseQuery('"volt typhoon" volt')), [
    [0, 12],
    [17, 21],
  ]);
  assert.deepEqual(queryRanges('nothing here', parseQuery('absent')), []);
  assert.deepEqual(queryRanges('anything', []), []);
});

test('queryRanges maps decomposed accents back to whole characters', () => {
  assert.deepEqual(queryRanges('Kyiv – Café', ['cafe']), [[7, 11]]);
  const text = 'Zelenskyy met Ze\u0301lenskyy'; // e + combining acute accent
  assert.deepEqual(queryRanges(text, ['zelenskyy']), [
    [0, 9],
    [14, 24],
  ]);
});

test('highlightSegments layers watch and search ranges', () => {
  assert.deepEqual(highlightSegments('Lazarus hits npm', { watch: [[0, 7]], search: [[4, 11]] }), [
    { text: 'Laza', kinds: ['watch'] },
    { text: 'rus', kinds: ['watch', 'search'] },
    { text: ' hit', kinds: ['search'] },
    { text: 's npm', kinds: [] },
  ]);
  assert.deepEqual(highlightSegments('plain', { watch: [], search: [] }), [{ text: 'plain', kinds: [] }]);
});

test('search uses whole words, with * for prefixes, like the watchlist', () => {
  assert.ok(!matchesQuery(fold('APT28 returns'), parseQuery('APT2')));
  assert.ok(matchesQuery(fold('APT28 returns'), parseQuery('APT2*')));
  assert.ok(!matchesQuery(fold('supply chains'), parseQuery('"supply chain"')));
  assert.ok(matchesQuery(fold('supply chains'), parseQuery('"supply chain"*')));
  assert.ok(matchesQuery(fold('Ransomware hits'), parseQuery('ransom*')));
  assert.ok(matchesQuery(fold('A C++ bug'), parseQuery('c++')));
  assert.deepEqual(parseQuery('ransom** "volt typhoon"*  *'), ['ransom*', 'volt typhoon*']);
});

test('queryRanges highlights exactly what matched', () => {
  assert.deepEqual(queryRanges('Worker forums or efforts', ['or']), [[14, 16]]);
  assert.deepEqual(queryRanges('Russian and Russia', ['russia']), [[12, 18]]);
  assert.deepEqual(queryRanges('Russian and Russia', ['russia*']), [
    [0, 7],
    [12, 18],
  ]);
});

test('prefixSuggestion turns bare words into prefixes', () => {
  assert.equal(prefixSuggestion('ransom'), 'ransom*');
  assert.equal(prefixSuggestion('ransom "volt typhoon" cve*'), 'ransom* "volt typhoon" cve*');
  assert.equal(prefixSuggestion('"exact" cve*'), null);
  assert.equal(prefixSuggestion('us'), null); // too short to be a useful prefix
});
