// Filtering and search. Pure functions so they can be unit tested in Node.

export const VIEWS = ['all', 'new', 'unread', 'saved', 'watchlist'];

/**
 * Lowercase, strip accents and straighten curly quotes, so "cafe" finds "Café" and "Yemen's"
 * finds "Yemen’s". Quotes map one-to-one, so queryRanges' offsets stay right.
 */
export function fold(text) {
  return String(text ?? '')
    .normalize('NFD')
    .replace(/\p{Diacritic}/gu, '')
    .replace(/[‘’ʼ′]/g, "'")
    .replace(/[“”″]/g, '"')
    .toLowerCase();
}

/**
 * Split a query into folded tokens; "quoted phrases" stay together. A trailing * (on a word or
 * after a closing quote) makes the token a prefix: ransom* finds "ransomware".
 */
export function parseQuery(query) {
  const tokens = [];
  for (const m of String(query ?? '').matchAll(/"([^"]+)"(\*?)|(\S+)/g)) {
    const raw = m[1] != null ? `${m[1].trim()}${m[2]}` : m[3].replace(/^"+/, ''); // a quote still being typed is not part of the word
    const token = fold(raw).replace(/\*+$/, '*');
    if (token && token !== '*') tokens.push(token);
  }
  return tokens;
}

/**
 * The same query with each bare word of 3+ letters turned into a prefix ("ransom" → "ransom*"),
 * or null when nothing would change. Quoted phrases and words that already end in * are kept.
 */
export function prefixSuggestion(query) {
  let changed = false;
  const next = String(query ?? '').replace(/"[^"]*"\*?|\S+/g, (part) => {
    if (part.startsWith('"') || part.endsWith('*') || part.length < 3) return part;
    changed = true;
    return `${part}*`;
  });
  return changed ? next.trim() : null;
}

// One matching rule for search and the watchlist: whole words or phrases, so "APT2" never finds
// "APT28"; a token ending in * also matches longer words that start with it.
const WORD = '[\\p{L}\\p{N}_]';
const tokenRegexes = new Map();
function tokenRegex(token) {
  let regex = tokenRegexes.get(token);
  if (!regex) {
    const prefix = token.length > 1 && token.endsWith('*');
    const core = prefix ? token.slice(0, -1) : token;
    const escaped = core.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    regex = new RegExp(`(?<!${WORD})${escaped}${prefix ? `${WORD}*` : ''}(?!${WORD})`, 'gu');
    if (tokenRegexes.size > 500) tokenRegexes.clear();
    tokenRegexes.set(token, regex);
  }
  regex.lastIndex = 0;
  return regex;
}

export function matchesQuery(searchText, tokens) {
  return tokens.every((token) => tokenRegex(token).test(searchText));
}

/**
 * Apply view, category, source and search filters.
 * ctx: { view, hiddenCategories: Set, hiddenSources: Set, tokens, isRead(id), isNew(item), isSaved(id), watchTerm? }
 * Items need: id, source, category, searchText, watch (array of matched terms).
 */
export function filterItems(items, ctx) {
  return items.filter((item) => {
    if (ctx.hiddenCategories.has(item.category)) return false;
    if (ctx.hiddenSources.has(item.source)) return false;
    switch (ctx.view) {
      case 'new':
        if (!ctx.isNew(item)) return false;
        break;
      case 'unread':
        if (ctx.isRead(item.id)) return false;
        break;
      case 'saved':
        if (!ctx.isSaved(item.id)) return false;
        break;
      case 'watchlist':
        if (!item.watch.length) return false;
        if (ctx.watchTerm && !item.watch.includes(ctx.watchTerm)) return false; // one term's hits
        break;
      default:
        break;
    }
    return !ctx.tokens.length || matchesQuery(item.searchText, ctx.tokens);
  });
}

/** Newest first by publication time, then by when Owlfeed first saw the item. */
export function sortItems(items) {
  return [...items].sort((a, b) => b.publishedMs - a.publishedMs || b.firstSeenMs - a.firstSeenMs);
}

/**
 * Where the search tokens occur in `text`, as merged [start, end) ranges of the original string.
 * Uses the same folding and word rule as the search, so "cafe" highlights "Café" and what is
 * highlighted is exactly what matched.
 */
export function queryRanges(text, tokens) {
  const source = String(text ?? '');
  if (!tokens?.length || !source) return [];
  let folded = '';
  const origin = []; // origin[i]: index in `source` of the character that produced folded[i]
  let index = 0;
  for (const char of source) {
    const part = fold(char);
    for (let k = 0; k < part.length; k += 1) origin.push(index);
    folded += part;
    index += char.length;
  }
  const ranges = [];
  for (const token of tokens) {
    for (const m of folded.matchAll(tokenRegex(token))) {
      if (!m[0]) continue;
      const at = m.index;
      const last = origin[at + m[0].length - 1];
      let end = source.length;
      for (let j = at + m[0].length; j < origin.length; j += 1) {
        if (origin[j] > last) {
          end = origin[j];
          break;
        }
      }
      ranges.push([origin[at], end]);
    }
  }
  return mergeRanges(ranges);
}

export function mergeRanges(ranges) {
  const sorted = [...ranges].sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const merged = [];
  for (const [start, end] of sorted) {
    const prev = merged[merged.length - 1];
    if (prev && start <= prev[1]) prev[1] = Math.max(prev[1], end);
    else merged.push([start, end]);
  }
  return merged;
}

/**
 * Split text into [{ text, kinds }] runs, where kinds lists the highlight layers covering the run
 * (e.g. ['watch'], ['search'] or both). layers: { name: [[start, end], ...] }.
 */
export function highlightSegments(text, layers) {
  const source = String(text ?? '');
  const cuts = new Set([0, source.length]);
  for (const ranges of Object.values(layers)) {
    for (const [start, end] of ranges) cuts.add(start).add(end);
  }
  const points = [...cuts].sort((a, b) => a - b);
  const segments = [];
  for (let i = 0; i < points.length - 1; i += 1) {
    const [start, end] = [points[i], points[i + 1]];
    if (start === end) continue;
    const kinds = Object.entries(layers)
      .filter(([, ranges]) => ranges.some(([s, e]) => s <= start && end <= e))
      .map(([name]) => name);
    const prev = segments[segments.length - 1];
    if (prev && prev.kinds.join() === kinds.join()) prev.text += source.slice(start, end);
    else segments.push({ text: source.slice(start, end), kinds });
  }
  return segments;
}
