// Watchlist matching: case-insensitive whole-phrase matches, safe for any characters.

export const MAX_TERM_LENGTH = 80;

export function normalizeTerm(term) {
  return String(term ?? '')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/\s*\*+$/, '*') // "Russia **" → "Russia*"
    .slice(0, MAX_TERM_LENGTH);
}

/** A trailing * makes a prefix term: "Russia*" also matches "Russian" and "Russians". */
export function isPrefixTerm(term) {
  return term.length > 1 && term.endsWith('*');
}

/** Add a term unless it is empty or already present (ignoring case). */
export function addTerm(terms, term) {
  const clean = normalizeTerm(term);
  if (!clean || terms.some((t) => t.toLowerCase() === clean.toLowerCase())) {
    return { terms, added: false };
  }
  return { terms: [...terms, clean], added: true };
}

export function removeTerm(terms, term) {
  return terms.filter((t) => t.toLowerCase() !== String(term).toLowerCase());
}

function escapeRegExp(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * Build a matcher for the given terms, or null when there are none.
 * Terms match whole words/phrases ("APT2" does not match "APT28"); a term ending in * also
 * matches longer words that start with it ("Russia*" matches "Russian").
 */
export function buildMatcher(terms) {
  const clean = [...new Set(terms.map(normalizeTerm).filter((t) => t && t !== '*'))];
  if (!clean.length) return null;
  const core = (term) => (isPrefixTerm(term) ? term.slice(0, -1) : term);
  // Longest first so "Lazarus Group" wins over "Lazarus". Each term is its own capture group,
  // so a match reports the term that caught it (in its saved spelling, star included).
  const ordered = [...clean].sort((a, b) => core(b).length - core(a).length);
  const groups = ordered.map((t) => `(${escapeRegExp(core(t))}${isPrefixTerm(t) ? '[\\p{L}\\p{N}_]*' : ''})`);
  const source = `(?<![\\p{L}\\p{N}_])(?:${groups.join('|')})(?![\\p{L}\\p{N}_])`;
  const regex = () => new RegExp(source, 'giu');
  const termOf = (m) => ordered[m.slice(1).findIndex((group) => group !== undefined)];

  return {
    /** Terms (in their saved spelling) found in any of the given texts. */
    match(...texts) {
      const found = new Set();
      for (const text of texts) {
        if (!text) continue;
        for (const m of text.matchAll(regex())) found.add(termOf(m));
      }
      return [...found];
    },
    /** Matched [start, end) ranges in text, for layering with other highlights. */
    ranges(text) {
      return [...String(text ?? '').matchAll(regex())].map((m) => [m.index, m.index + m[0].length]);
    },
    /** Split text into [{ text, match }] parts for highlighting. */
    parts(text) {
      const parts = [];
      let last = 0;
      for (const m of String(text ?? '').matchAll(regex())) {
        if (m.index > last) parts.push({ text: text.slice(last, m.index), match: false });
        parts.push({ text: m[0], match: true });
        last = m.index + m[0].length;
      }
      if (last < String(text ?? '').length) parts.push({ text: text.slice(last), match: false });
      return parts;
    },
  };
}
