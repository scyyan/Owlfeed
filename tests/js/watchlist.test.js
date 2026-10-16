import assert from 'node:assert/strict';
import { test } from 'node:test';

import { addTerm, buildMatcher, normalizeTerm, removeTerm } from '../../site/js/watchlist.js';

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
