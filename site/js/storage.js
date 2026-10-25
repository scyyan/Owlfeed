// Per-browser state: read items, saved items, watchlist, filter preferences, last visit.
// Everything lives in localStorage (never sent anywhere). If storage is unavailable
// (private mode, blocked site data) the dashboard still works for the current visit.
//
// Several tabs can be open at once, so every change re-reads the stored value right before
// writing (read-modify-write) instead of writing back a possibly stale in-memory copy, and
// other tabs' changes arrive through the browser's "storage" event (see listen()).

import { cleanTerms, MAX_TERMS, normalizeTerm } from './watchlist.js';

const PREFIX = 'owlfeed:v1:';
// A restore adds at most this many saved items and read marks (bounds a huge or hostile file).
export const MAX_IMPORT_ENTRIES = 20_000;
const READ_TTL_DAYS = 30;
const DAY = 86_400_000;

export const DENSITIES = ['comfortable', 'compact'];
export const DEFAULT_PREFS = Object.freeze({ view: 'all', hiddenCategories: [], hiddenSources: [], density: 'comfortable', shortcuts: true });

function defaultBackend() {
  try {
    return globalThis.localStorage ?? null;
  } catch {
    return null;
  }
}

function isPlainObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

/** Item ids become object keys; never use one that names a built-in property. */
function isSafeKey(id) {
  return typeof id === 'string' && id !== '__proto__' && !(id in Object.prototype);
}

function stringList(value) {
  return Array.isArray(value) ? value.filter((v) => typeof v === 'string') : [];
}

function isHttpUrl(value) {
  try {
    const { protocol } = new URL(value);
    return protocol === 'http:' || protocol === 'https:';
  } catch {
    return false;
  }
}

function cleanSnapshot(value) {
  if (!isPlainObject(value) || typeof value.id !== 'string' || typeof value.title !== 'string') return null;
  if (!isHttpUrl(value.url)) return null;
  const text = (key) => (typeof value[key] === 'string' ? value[key] : '');
  return {
    id: value.id,
    title: value.title,
    url: value.url,
    summary: text('summary'),
    source: text('source'),
    sourceName: text('sourceName'),
    category: text('category'),
    published: text('published'),
    first_seen: text('first_seen'),
    savedAt: text('savedAt'),
  };
}

export function createStorage(backend = defaultBackend()) {
  const memory = new Map();
  // Keys whose latest value only exists in memory because storage refused it (blocked or full).
  // Memory is the source of truth for them, so later changes build on it instead of starting over.
  const memoryOnly = new Set();

  function readBackend(key, fallback) {
    if (!backend || memoryOnly.has(key)) return memory.has(key) ? memory.get(key) : fallback;
    try {
      const raw = backend.getItem(PREFIX + key);
      return raw == null ? fallback : JSON.parse(raw);
    } catch {
      return memory.has(key) ? memory.get(key) : fallback;
    }
  }

  function load(key, fallback) {
    if (!memory.has(key)) memory.set(key, readBackend(key, fallback));
    return memory.get(key);
  }

  /** Store a value; returns false when it only lives in memory (storage full or blocked). */
  function save(key, value) {
    memory.set(key, value);
    if (!backend) {
      memoryOnly.add(key);
      return false;
    }
    try {
      backend.setItem(PREFIX + key, JSON.stringify(value));
      memoryOnly.delete(key);
      return true;
    } catch {
      memoryOnly.add(key); // storage full or blocked: keep working from memory for this visit
      return false;
    }
  }

  /** Apply a change to the freshest stored copy, so another tab's writes are not lost. */
  function update(key, fallback, change) {
    const current = readBackend(key, fallback);
    return save(key, change(current));
  }

  const asObject = (value) => (isPlainObject(value) ? value : {});
  const readMap = () => asObject(load('read', {}));
  const savedMap = () => asObject(load('saved', {}));

  return {
    /** Forget cached values (all, or one key) so the next read comes from storage. */
    invalidate(key) {
      const keys = key == null ? [...memory.keys()] : [key];
      for (const k of keys) if (!memoryOnly.has(k)) memory.delete(k);
    },

    /** Call onChange(key) when another tab changes a stored value. Returns an unsubscribe function. */
    listen(onChange, target = globalThis) {
      const handler = (event) => {
        if (event.key !== null && !event.key?.startsWith(PREFIX)) return;
        const key = event.key === null ? null : event.key.slice(PREFIX.length);
        this.invalidate(key);
        onChange(key);
      };
      target.addEventListener?.('storage', handler);
      return () => target.removeEventListener?.('storage', handler);
    },

    isRead: (id) => Object.hasOwn(readMap(), id),
    readCount: () => Object.keys(readMap()).length,
    setRead(ids, read = true, now = Date.now()) {
      update('read', {}, (current) => {
        const next = { ...asObject(current) };
        for (const id of ids) {
          if (read) next[id] = now;
          else delete next[id];
        }
        return next;
      });
    },
    /**
     * Forget read marks older than the retention window to keep storage small. Saved items keep
     * theirs: they stay on the Saved list long after the feed drops them.
     */
    pruneRead(now = Date.now()) {
      const cutoff = now - READ_TTL_DAYS * DAY;
      const saved = asObject(readBackend('saved', {}));
      update('read', {}, (current) =>
        Object.fromEntries(
          Object.entries(asObject(current)).filter(
            ([id, at]) => typeof at === 'number' && (at >= cutoff || Object.hasOwn(saved, id)),
          ),
        ),
      );
    },

    isSaved(id) {
      const saved = savedMap();
      return Object.hasOwn(saved, id) && cleanSnapshot(saved[id]) !== null;
    },
    // Validated on read too: a damaged entry (devtools, another page on this origin) must not break the app.
    savedItems: () => Object.values(savedMap()).map(cleanSnapshot).filter(Boolean),
    setSaved(snapshot, saved = true) {
      const clean = saved ? cleanSnapshot(snapshot) : null;
      if (saved && !clean) return false;
      update('saved', {}, (current) => {
        const next = { ...asObject(current) };
        if (saved) next[clean.id] = clean;
        else delete next[snapshot.id];
        return next;
      });
      return true;
    },

    // Cleaned on read, so older stored lists (untidy, duplicated or oversized) still work.
    watchlist: () => cleanTerms(stringList(load('watchlist', []))),
    setWatchlist: (terms) => save('watchlist', stringList(terms)),
    /** Change the watchlist against the freshest stored copy; change(terms) returns the new list. */
    updateWatchlist(change) {
      update('watchlist', [], (current) => cleanTerms(stringList(change(cleanTerms(stringList(current))))));
      return this.watchlist();
    },

    prefs() {
      const value = load('prefs', null);
      const prefs = isPlainObject(value) ? value : {};
      return {
        view: typeof prefs.view === 'string' ? prefs.view : DEFAULT_PREFS.view,
        hiddenCategories: stringList(prefs.hiddenCategories),
        hiddenSources: stringList(prefs.hiddenSources),
        // No stored choice yet: the app picks the default (comfortable).
        density: DENSITIES.includes(prefs.density) ? prefs.density : null,
        // Single-key shortcuts (j, k, d, 1–5...) are on unless the reader turned them off.
        shortcuts: prefs.shortcuts !== false,
      };
    },
    setPrefs: (prefs) => save('prefs', prefs),

    /** The newest feed build (its generated_at, server time) this reader has had on screen. */
    lastVisit() {
      const value = load('lastVisit', null);
      return typeof value === 'string' && Number.isFinite(Date.parse(value)) ? value : null;
    },
    /** Only ever moves forward, so an older tab closing later cannot rewind it. */
    advanceLastVisit(iso) {
      if (!Number.isFinite(Date.parse(iso))) return;
      update('lastVisit', null, (current) =>
        typeof current === 'string' && Date.parse(current) >= Date.parse(iso) ? current : iso,
      );
    },

    theme() {
      const value = load('theme', null);
      return value === 'light' || value === 'dark' ? value : null;
    },
    setTheme: (theme) => save('theme', theme),

    /** Everything worth carrying to another browser, as a plain object. */
    exportData(now = new Date()) {
      this.invalidate();
      return {
        app: 'owlfeed',
        version: 1,
        exportedAt: now.toISOString(),
        watchlist: this.watchlist(),
        saved: savedMap(),
        read: readMap(),
        prefs: this.prefs(),
      };
    },

    /** Merge a backup into this browser. Returns what was added, or throws on a foreign file. */
    importData(data, now = new Date()) {
      if (!isPlainObject(data) || data.app !== 'owlfeed') {
        throw new Error('This file is not an Owlfeed backup.');
      }
      let termsAdded = 0;
      let persisted = true;
      persisted = update('watchlist', [], (current) => {
        const terms = cleanTerms(stringList(current));
        // Imported terms get the same cleanup as typed ones, so each chip can match its hits.
        const lower = new Set(terms.map((t) => t.toLowerCase()));
        const fresh = [];
        for (const term of stringList(data.watchlist).map(normalizeTerm)) {
          if (terms.length + fresh.length >= MAX_TERMS) break;
          if (!term || term === '*' || lower.has(term.toLowerCase())) continue;
          lower.add(term.toLowerCase());
          fresh.push(term);
        }
        termsAdded = fresh.length;
        return [...terms, ...fresh];
      }) && persisted;

      let savedAdded = 0;
      persisted = update('saved', {}, (current) => {
        const saved = { ...asObject(current) };
        for (const value of Object.values(asObject(data.saved)).slice(0, MAX_IMPORT_ENTRIES)) {
          const clean = cleanSnapshot(value);
          if (clean && isSafeKey(clean.id) && !Object.hasOwn(saved, clean.id)) {
            saved[clean.id] = clean;
            savedAdded += 1;
          }
        }
        return saved;
      }) && persisted;

      persisted = update('read', {}, (current) => {
        const read = { ...asObject(current) };
        const latest = now.getTime();
        for (const [id, at] of Object.entries(asObject(data.read)).slice(0, MAX_IMPORT_ENTRIES)) {
          if (!isSafeKey(id) || !Number.isFinite(at)) continue;
          // A mark from the future would never be pruned.
          const mark = Math.min(at, latest);
          read[id] = Object.hasOwn(read, id) && Number.isFinite(read[id]) ? Math.max(read[id], mark) : mark;
        }
        return read;
      }) && persisted;

      if (isPlainObject(data.prefs)) {
        persisted = save('prefs', {
          view: typeof data.prefs.view === 'string' ? data.prefs.view : DEFAULT_PREFS.view,
          hiddenCategories: stringList(data.prefs.hiddenCategories),
          hiddenSources: stringList(data.prefs.hiddenSources),
          density: DENSITIES.includes(data.prefs.density) ? data.prefs.density : DEFAULT_PREFS.density,
          shortcuts: data.prefs.shortcuts !== false,
        }) && persisted;
      }
      // persisted: false means some of it is only kept for this visit (storage full or blocked).
      return { terms: termsAdded, saved: savedAdded, persisted };
    },
  };
}
