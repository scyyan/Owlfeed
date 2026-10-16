// Filtering and search. Pure functions so they can be unit tested in Node.

export const VIEWS = ['all', 'new', 'unread', 'saved', 'watchlist'];

/** Lowercase and strip accents so "Zelenskyy" finds "Zelenskyy" and "café" finds "cafe". */
export function fold(text) {
  return String(text ?? '')
    .normalize('NFD')
    .replace(/\p{Diacritic}/gu, '')
    .toLowerCase();
}

/** Split a query into folded tokens; "quoted phrases" stay together. */
export function parseQuery(query) {
  const tokens = [];
  for (const m of String(query ?? '').matchAll(/"([^"]+)"|(\S+)/g)) {
    const token = fold((m[1] ?? m[2]).trim());
    if (token) tokens.push(token);
  }
  return tokens;
}

export function matchesQuery(searchText, tokens) {
  return tokens.every((token) => searchText.includes(token));
}

/**
 * Apply view, category, source and search filters.
 * ctx: { view, hiddenCategories: Set, hiddenSources: Set, tokens, isRead(id), isNew(item), isSaved(id) }
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
