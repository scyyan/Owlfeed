// Watchlist matching: case-insensitive whole-phrase matches, safe for any characters.

export const MAX_TERM_LENGTH = 80;

export function normalizeTerm(term) {
  return String(term ?? '').replace(/\s+/g, ' ').trim().slice(0, MAX_TERM_LENGTH);
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
 * Terms only match as whole words/phrases: "APT2" does not match "APT28".
 */
export function buildMatcher(terms) {
  const clean = [...new Set(terms.map(normalizeTerm).filter(Boolean))];
  if (!clean.length) return null;
  const byLower = new Map(clean.map((t) => [t.toLowerCase(), t]));
  // Longest first so "Lazarus Group" wins over "Lazarus".
  const alternation = [...clean].sort((a, b) => b.length - a.length).map(escapeRegExp).join('|');
  const source = `(?<![\\p{L}\\p{N}_])(?:${alternation})(?![\\p{L}\\p{N}_])`;
  const regex = () => new RegExp(source, 'giu');

  return {
    /** Terms (in their saved spelling) found in any of the given texts. */
    match(...texts) {
      const found = new Set();
      for (const text of texts) {
        if (!text) continue;
        for (const m of text.matchAll(regex())) {
          found.add(byLower.get(m[0].toLowerCase()) ?? m[0]);
        }
      }
      return [...found];
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
