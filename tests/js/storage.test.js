import assert from 'node:assert/strict';
import { test } from 'node:test';

import { createStorage } from '../../site/js/storage.js';

class MemoryBackend {
  constructor() {
    this.data = new Map();
  }
  getItem(key) {
    return this.data.has(key) ? this.data.get(key) : null;
  }
  setItem(key, value) {
    this.data.set(key, String(value));
  }
}

class BrokenBackend {
  getItem() {
    throw new Error('SecurityError');
  }
  setItem() {
    throw new Error('QuotaExceededError');
  }
}

const SNAPSHOT = {
  id: 'a1',
  title: 'Saved story',
  url: 'https://example.com/a1',
  summary: 'Summary',
  source: 'alpha',
  sourceName: 'Alpha',
  category: 'Cyber',
  published: '2026-10-15T13:00:00Z',
  first_seen: '2026-10-15T13:05:00Z',
  savedAt: '2026-10-15T14:00:00Z',
};

test('read state persists across instances', () => {
  const backend = new MemoryBackend();
  const store = createStorage(backend);
  store.setRead(['a', 'b']);
  store.setRead(['b'], false);
  const again = createStorage(backend);
  assert.ok(again.isRead('a'));
  assert.ok(!again.isRead('b'));
  assert.equal(again.readCount(), 1);
});

test('old read marks are pruned', () => {
  const store = createStorage(new MemoryBackend());
  const now = Date.parse('2026-10-15T14:00:00Z');
  store.setRead(['old'], true, now - 40 * 86_400_000);
  store.setRead(['recent'], true, now - 86_400_000);
  store.pruneRead(now);
  assert.ok(!store.isRead('old'));
  assert.ok(store.isRead('recent'));
});

test('saved snapshots are validated', () => {
  const store = createStorage(new MemoryBackend());
  store.setSaved(SNAPSHOT);
  store.setSaved({ ...SNAPSHOT, id: 'evil', url: 'javascript:alert(1)' });
  assert.ok(store.isSaved('a1'));
  assert.ok(!store.isSaved('evil'));
  assert.equal(store.savedItems()[0].title, 'Saved story');
  store.setSaved({ id: 'a1' }, false);
  assert.ok(!store.isSaved('a1'));
});

test('prefs fall back to defaults when corrupted', () => {
  const backend = new MemoryBackend();
  backend.setItem('owlfeed:v1:prefs', '{"view": 42, "hiddenSources": "nope"}');
  backend.setItem('owlfeed:v1:watchlist', 'not json');
  const store = createStorage(backend);
  assert.deepEqual(store.prefs(), { view: 'all', hiddenCategories: [], hiddenSources: [], density: null });
  assert.deepEqual(store.watchlist(), []);
});

test('works in memory when storage is blocked or missing', () => {
  for (const backend of [new BrokenBackend(), null]) {
    const store = createStorage(backend);
    store.updateWatchlist((terms) => [...terms, 'APT28']);
    store.updateWatchlist((terms) => [...terms, 'Volt Typhoon']);
    store.setRead(['x']);
    store.setRead(['y']);
    store.setSaved(SNAPSHOT);
    store.setSaved({ ...SNAPSHOT, id: 'b2' });
    store.invalidate(); // e.g. before a backup: memory-only values must survive
    assert.deepEqual(store.watchlist(), ['APT28', 'Volt Typhoon']);
    assert.ok(store.isRead('x') && store.isRead('y'));
    assert.equal(store.savedItems().length, 2);
    assert.equal(Object.keys(store.exportData().read).length, 2);
    assert.equal(store.theme(), null);
  }
});

test('export and import round trip merges without duplicates', () => {
  const source = createStorage(new MemoryBackend());
  source.setWatchlist(['APT28', 'Volt Typhoon']);
  source.setSaved(SNAPSHOT);
  source.setRead(['r1'], true, 1000);
  source.setPrefs({ view: 'unread', hiddenCategories: ['Geopolitics'], hiddenSources: [] });
  const backup = JSON.parse(JSON.stringify(source.exportData(new Date('2026-10-15T14:00:00Z'))));
  assert.equal(backup.app, 'owlfeed');

  const target = createStorage(new MemoryBackend());
  target.updateWatchlist(() => ['apt28']);
  const result = target.importData(backup);
  assert.deepEqual(result, { terms: 1, saved: 1 });
  assert.deepEqual(target.watchlist(), ['apt28', 'Volt Typhoon']);
  assert.ok(target.isSaved('a1') && target.isRead('r1'));
  assert.equal(target.prefs().view, 'unread');
  assert.throws(() => target.importData({ hello: 'world' }), /not an Owlfeed backup/);
});

test('two tabs never overwrite each other', () => {
  const backend = new MemoryBackend();
  const tabA = createStorage(backend);
  const tabB = createStorage(backend);
  assert.ok(!tabA.isRead('x') && !tabB.isRead('y')); // both tabs have cached their (empty) maps
  tabA.setRead(['x']);
  tabB.setRead(['y']);
  tabA.setSaved(SNAPSHOT);
  tabB.setSaved({ ...SNAPSHOT, id: 'b2' });
  tabA.updateWatchlist((terms) => [...terms, 'APT28']);
  tabB.updateWatchlist((terms) => [...terms, 'Volt Typhoon']);
  const fresh = createStorage(backend);
  assert.ok(fresh.isRead('x') && fresh.isRead('y'));
  assert.ok(fresh.isSaved('a1') && fresh.isSaved('b2'));
  assert.deepEqual(fresh.watchlist(), ['APT28', 'Volt Typhoon']);
});

test('storage events from another tab invalidate the cache', () => {
  const backend = new MemoryBackend();
  const tabA = createStorage(backend);
  const tabB = createStorage(backend);
  const target = new EventTarget();
  const changes = [];
  tabB.listen((key) => changes.push(key), target);
  assert.ok(!tabB.isRead('x'));
  tabA.setRead(['x']);
  const event = new Event('storage');
  event.key = 'owlfeed:v1:read';
  target.dispatchEvent(event);
  assert.deepEqual(changes, ['read']);
  assert.ok(tabB.isRead('x'));
  const unrelated = new Event('storage');
  unrelated.key = 'someone-else';
  target.dispatchEvent(unrelated);
  assert.deepEqual(changes, ['read']);
});

test('last visit only moves forward', () => {
  const store = createStorage(new MemoryBackend());
  assert.equal(store.lastVisit(), null);
  store.advanceLastVisit('2026-10-15T14:00:00Z');
  store.advanceLastVisit('2026-10-15T13:00:00Z');
  store.advanceLastVisit('not a date');
  assert.equal(store.lastVisit(), '2026-10-15T14:00:00Z');
});

test('setSaved reports whether a snapshot was stored', () => {
  const store = createStorage(new MemoryBackend());
  assert.equal(store.setSaved(SNAPSHOT), true);
  assert.equal(store.setSaved({ id: 'nope', title: 'x', url: 'ftp://x' }), false);
});
