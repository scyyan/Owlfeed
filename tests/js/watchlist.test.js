import assert from 'node:assert/strict';
import { test } from 'node:test';

import { addTerm, buildMatcher, cleanTerms, MAX_TERMS, normalizeTerm, removeTerm } from '../../site/js/watchlist.js';

test('normalizeTerm trims and collapses whitespace', () => {
  assert.equal(normalizeTerm('  Lazarus   Group '), 'Lazarus Group');
  assert.equal(normalizeTerm(null), '');
  assert.equal(normalizeTerm('x'.repeat(200)).length, 80);
});

test('addTerm ignores empty and duplicate terms', () => {
  assert.deepEqual(addTerm(['APT28'], 'apt28'), { terms: ['APT28'], added: false });
  assert.deepEqual(addTerm(['APT28'], '   '), { terms: ['APT28'], added: false });
  assert.deepEqual(addTerm(['APT28'], 'Volt Typhoon'), { terms: ['APT28', 'Volt Typhoon'], added: true });
  assert.deepEqual(removeTerm(['APT28', 'Volt Typhoon'], 'apt28'), ['Volt Typhoon']);
});

test('no terms means no matcher', () => {
  assert.equal(buildMatcher([]), null);
  assert.equal(buildMatcher(['  ']), null);
});

test('matches whole words case-insensitively and reports saved spelling', () => {
  const matcher = buildMatcher(['APT28', 'ransomware']);
  assert.deepEqual(matcher.match('New apt28 campaign', 'Ransomware hits hospitals'), ['APT28', 'ransomware']);
  assert.deepEqual(matcher.match('APT2 and APT280 are different', 'ransomwares'), []);
});

test('phrases, punctuation and unicode are safe', () => {
  const matcher = buildMatcher(['C++', '.NET', 'Zelenskyy', 'Kyiv (Kiev)', 'Ελλάδα']);
  assert.deepEqual(matcher.match('A C++ and .NET bug'), ['C++', '.NET']);
  assert.deepEqual(matcher.match('Zelenskyy visits Kyiv (Kiev) today'), ['Zelenskyy', 'Kyiv (Kiev)']);
  assert.deepEqual(matcher.match('Νέα από την Ελλάδα'), ['Ελλάδα']);
});

test('longer terms win over their prefixes', () => {
  const matcher = buildMatcher(['Lazarus', 'Lazarus Group']);
  assert.deepEqual(
    matcher.parts('The Lazarus Group struck'),
    [
      { text: 'The ', match: false },
      { text: 'Lazarus Group', match: true },
      { text: ' struck', match: false },
    ],
  );
});

test('parts covers the whole text', () => {
  const matcher = buildMatcher(['cve']);
  const text = 'CVE at start, cve in middle and CVE';
  assert.equal(matcher.parts(text).map((p) => p.text).join(''), text);
  assert.equal(matcher.parts(text).filter((p) => p.match).length, 3);
  assert.deepEqual(matcher.parts('nothing here'), [{ text: 'nothing here', match: false }]);
});

test('a trailing * matches longer words; plain terms stay whole-word', () => {
  const matcher = buildMatcher(['Russia*', 'APT2']);
  assert.deepEqual(matcher.match('Russian hackers and Russia’s army'), ['Russia*']);
  assert.deepEqual(matcher.match('APT28 is not APT2s'), []);
  assert.deepEqual(matcher.ranges('Russians'), [[0, 8]]);
  assert.deepEqual(buildMatcher(['Belarus']).match('Belarusian forces'), []);
});

test('normalizeTerm tidies stars and a lone star is ignored', () => {
  assert.equal(normalizeTerm('Russia **'), 'Russia*');
  assert.equal(buildMatcher(['*']), null);
  assert.deepEqual(buildMatcher(['C++']).match('C++ bug'), ['C++']);
});

test('addTerm rejects a lone star', () => {
  assert.deepEqual(addTerm([], '***'), { terms: [], added: false });
});

test('terms ignore accents, capitals and curly quotes, like the search', () => {
  assert.deepEqual(buildMatcher(['Erdogan']).match('Erdoğan meets Putin'), ['Erdogan']);
  assert.deepEqual(buildMatcher(['Sao Paulo']).match('Floods in São Paulo'), ['Sao Paulo']);
  assert.deepEqual(buildMatcher(['istanbul']).match('İSTANBUL'), ['istanbul']);
  assert.deepEqual(buildMatcher(['café']).match('café attack'), ['café']); // decomposed accent in the feed
  assert.deepEqual(buildMatcher(["People's Liberation Army"]).match('The People’s Liberation Army drills'), ["People's Liberation Army"]);
  assert.deepEqual(buildMatcher(['Erdogan']).ranges('Mr Erdoğan said'), [[3, 10]]);
});

test('every term is credited, even when a longer one matches the same words', () => {
  assert.deepEqual(buildMatcher(['Lazarus', 'Lazarus Group']).match('The Lazarus Group strikes'), ['Lazarus', 'Lazarus Group']);
  assert.deepEqual(buildMatcher(['Russia*', 'Russia']).match('Russia warns'), ['Russia*', 'Russia']);
  assert.deepEqual(buildMatcher(['Russia', 'Russia*']).match('Russia warns'), ['Russia', 'Russia*']);
});

test('a huge list is capped instead of breaking the matcher', () => {
  const terms = Array.from({ length: 40_000 }, (_, i) => `w${i}`);
  const matcher = buildMatcher(terms);
  assert.deepEqual(matcher.match('w5 and w199 but not w200'), ['w5', 'w199']);
  assert.equal(cleanTerms(terms).length, MAX_TERMS);
  const full = cleanTerms(terms);
  assert.deepEqual(addTerm(full, 'one more'), { terms: full, added: false });
});

test('cleanTerms tidies and drops case-only duplicates', () => {
  assert.deepEqual(cleanTerms(['  Lazarus  ', 'lazarus', 'Russia *', '*', '', 'APT28']), ['Lazarus', 'Russia*', 'APT28']);
});
