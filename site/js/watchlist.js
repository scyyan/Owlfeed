// Watchlist matching: whole-phrase matches by the search's rules, safe for any characters.

import { fold, matchesQuery, queryRanges } from './filters.js';

export const MAX_TERM_LENGTH = 80;
// Far more than anyone tracks by hand; bounds what a restored backup can add.
export const MAX_TERMS = 200;

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

/** Add a term unless it is empty, already present (ignoring case) or the list is full. */
export function addTerm(terms, term) {
  const clean = normalizeTerm(term);
  if (!clean || clean === '*' || terms.length >= MAX_TERMS || terms.some((t) => t.toLowerCase() === clean.toLowerCase())) {
    return { terms, added: false };
  }
  return { terms: [...terms, clean], added: true };
}

export function removeTerm(terms, term) {
  return terms.filter((t) => t.toLowerCase() !== String(term).toLowerCase());
}

/**
 * The terms a watchlist can use: tidied, without empty or lone-star terms or case-only
 * duplicates, and at most MAX_TERMS of them (each term costs a pass over every item).
 */
export function cleanTerms(terms) {
  const seen = new Set();
  const clean = [];
  for (const term of terms) {
    const tidy = normalizeTerm(term);
    const key = tidy.toLowerCase();
    if (!tidy || tidy === '*' || seen.has(key)) continue;
    seen.add(key);
    clean.push(tidy);
    if (clean.length >= MAX_TERMS) break;
  }
  return clean;
}

/**
 * Build a matcher for the given terms, or null when there are none.
 * Terms follow the search's rule (filters.js): whole words/phrases ("APT2" does not match
 * "APT28"), accents, capitals and curly quotes ignored, and a term ending in * also matches longer
 * words that start with it ("Russia*" matches "Russian"). Every term is checked on its own, so
 * "Lazarus" and "Lazarus Group" both count a "Lazarus Group" headline.
 */
export function buildMatcher(terms) {
  const clean = cleanTerms(terms);
  if (!clean.length) return null;
  const tokens = clean.map((term) => fold(term));
  const ranges = (text) => queryRanges(text, tokens);

  return {
    /** Terms (in their saved spelling, in list order) found in any of the given texts. */
    match(...texts) {
      const folded = texts.filter(Boolean).map((text) => fold(text));
      if (!folded.length) return [];
      return clean.filter((_, i) => folded.some((text) => matchesQuery(text, [tokens[i]])));
    },
    /** Matched [start, end) ranges in text (merged), for layering with other highlights. */
    ranges,
    /** Split text into [{ text, match }] parts for highlighting. */
    parts(text) {
      const source = String(text ?? '');
      const parts = [];
      let last = 0;
      for (const [start, end] of ranges(source)) {
        if (start > last) parts.push({ text: source.slice(last, start), match: false });
        parts.push({ text: source.slice(start, end), match: true });
        last = end;
      }
      if (last < source.length) parts.push({ text: source.slice(last), match: false });
      return parts;
    },
  };
}
