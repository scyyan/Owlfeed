import assert from 'node:assert/strict';
import { test } from 'node:test';

import { dayKey, dayLabel, parseTime, relativeTime, updatedLabel } from '../../site/js/time.js';

const NOW = Date.parse('2026-10-15T14:00:00Z'); // tests run with TZ=UTC

test('relativeTime buckets', () => {
  assert.equal(relativeTime(NOW - 20_000, NOW), 'just now');
  assert.equal(relativeTime(NOW - 12 * 60_000, NOW), '12m ago');
  assert.equal(relativeTime(NOW - 3 * 3_600_000, NOW), '3h ago');
  assert.equal(relativeTime(NOW - 50 * 3_600_000, NOW), '2d ago');
  assert.equal(relativeTime(NOW + 60_000, NOW), 'just now'); // clock skew never shows negative ages
});

test('updatedLabel wording', () => {
  assert.equal(updatedLabel(NOW - 4 * 60_000, NOW), '4 min ago');
  assert.equal(updatedLabel(NOW - 3_600_000, NOW), '1 hour ago');
  assert.equal(updatedLabel(NOW - 5 * 3_600_000, NOW), '5 hours ago');
  assert.equal(updatedLabel(NOW - 2 * 86_400_000, NOW), '2 days ago');
});

test('parseTime rejects junk', () => {
  assert.equal(parseTime('2026-10-15T14:00:00Z'), NOW);
  assert.ok(Number.isNaN(parseTime('not a date')));
  assert.ok(Number.isNaN(parseTime(undefined)));
});

test('dayKey uses the local calendar day', () => {
  assert.equal(dayKey(Date.parse('2026-10-15T23:59:00Z')), '2026-10-15');
  assert.equal(dayKey(Date.parse('2026-10-16T00:01:00Z')), '2026-10-16');
});

test('dayLabel names today, yesterday and older days', () => {
  assert.equal(dayLabel(NOW - 3_600_000, NOW, 'en-US').title, 'Today');
  assert.equal(dayLabel(NOW - 86_400_000, NOW, 'en-US').title, 'Yesterday');
  const older = dayLabel(Date.parse('2026-10-12T09:00:00Z'), NOW, 'en-US');
  assert.equal(older.title, 'Monday');
  assert.equal(older.detail, 'Oct 12'); // the title already names the weekday
  assert.equal(dayLabel(NOW - 86_400_000, NOW, 'en-US').detail.split(',').length, 2); // Yesterday keeps it
  assert.match(dayLabel(Date.parse('2025-12-30T09:00:00Z'), NOW, 'en-US').detail, /2025/);
});
