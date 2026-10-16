// Per-browser state: read items, saved items, watchlist, filter preferences, last visit.
// Everything lives in localStorage (never sent anywhere). If storage is unavailable
// (private mode, blocked site data) the dashboard still works for the current visit.

const PREFIX = 'owlfeed:v1:';
const READ_TTL_DAYS = 30;
const DAY = 86_400_000;

export const DEFAULT_PREFS = Object.freeze({ view: 'all', hiddenCategories: [], hiddenSources: [] });

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

  function load(key, fallback) {
    if (memory.has(key)) return memory.get(key);
    let value = fallback;
    try {
      const raw = backend?.getItem(PREFIX + key);
      if (raw != null) value = JSON.parse(raw);
    } catch {
      value = fallback;
    }
    memory.set(key, value);
    return value;
  }

  function save(key, value) {
    memory.set(key, value);
    try {
      backend?.setItem(PREFIX + key, JSON.stringify(value));
    } catch {
      // Storage full or blocked: keep working from memory for this visit.
    }
  }

  const readMap = () => {
    const value = load('read', {});
    return isPlainObject(value) ? value : {};
  };
  const savedMap = () => {
    const value = load('saved', {});
    return isPlainObject(value) ? value : {};
  };

  return {
    isRead: (id) => Object.hasOwn(readMap(), id),
    readCount: () => Object.keys(readMap()).length,
    setRead(ids, read = true, now = Date.now()) {
      const next = { ...readMap() };
      for (const id of ids) {
        if (read) next[id] = now;
        else delete next[id];
      }
      save('read', next);
    },
    /** Forget read marks older than the retention window to keep storage small. */
    pruneRead(now = Date.now()) {
      const cutoff = now - READ_TTL_DAYS * DAY;
      const current = readMap();
      const next = Object.fromEntries(Object.entries(current).filter(([, at]) => typeof at === 'number' && at >= cutoff));
      if (Object.keys(next).length !== Object.keys(current).length) save('read', next);
    },

    isSaved: (id) => Object.hasOwn(savedMap(), id),
    savedItems: () => Object.values(savedMap()),
    setSaved(snapshot, saved = true) {
      const next = { ...savedMap() };
      if (saved) {
        const clean = cleanSnapshot(snapshot);
        if (!clean) return;
        next[clean.id] = clean;
      } else {
        delete next[snapshot.id];
      }
      save('saved', next);
    },

    watchlist: () => stringList(load('watchlist', [])),
    setWatchlist: (terms) => save('watchlist', stringList(terms)),

    prefs() {
      const value = load('prefs', DEFAULT_PREFS);
      const prefs = isPlainObject(value) ? value : {};
      return {
        view: typeof prefs.view === 'string' ? prefs.view : DEFAULT_PREFS.view,
        hiddenCategories: stringList(prefs.hiddenCategories),
        hiddenSources: stringList(prefs.hiddenSources),
      };
    },
    setPrefs: (prefs) => save('prefs', prefs),

    lastVisit() {
      const value = load('lastVisit', null);
      return typeof value === 'string' ? value : null;
    },
    setLastVisit: (iso) => save('lastVisit', iso),

    theme() {
      const value = load('theme', null);
      return value === 'light' || value === 'dark' ? value : null;
    },
    setTheme: (theme) => save('theme', theme),

    /** Everything worth carrying to another browser, as a plain object. */
    exportData(now = new Date()) {
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
    importData(data) {
      if (!isPlainObject(data) || data.app !== 'owlfeed') {
        throw new Error('This file is not an Owlfeed backup.');
      }
      const terms = this.watchlist();
      const lower = new Set(terms.map((t) => t.toLowerCase()));
      const newTerms = stringList(data.watchlist).filter((t) => t.trim() && !lower.has(t.toLowerCase()));
      this.setWatchlist([...terms, ...newTerms]);

      const saved = { ...savedMap() };
      let savedAdded = 0;
      for (const value of Object.values(isPlainObject(data.saved) ? data.saved : {})) {
        const clean = cleanSnapshot(value);
        if (clean && !saved[clean.id]) {
          saved[clean.id] = clean;
          savedAdded += 1;
        }
      }
      save('saved', saved);

      const read = { ...readMap() };
      for (const [id, at] of Object.entries(isPlainObject(data.read) ? data.read : {})) {
        if (typeof at === 'number') read[id] = Math.max(read[id] ?? 0, at);
      }
      save('read', read);

      if (isPlainObject(data.prefs)) {
        save('prefs', {
          view: typeof data.prefs.view === 'string' ? data.prefs.view : DEFAULT_PREFS.view,
          hiddenCategories: stringList(data.prefs.hiddenCategories),
          hiddenSources: stringList(data.prefs.hiddenSources),
        });
      }
      return { terms: newTerms.length, saved: savedAdded };
    },
  };
}
