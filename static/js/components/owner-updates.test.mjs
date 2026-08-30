import assert from 'node:assert/strict';
import test from 'node:test';

import {
  formatOwnerUpdateSummary,
  selectCompactOwnerUpdates,
  sortOwnerUpdates,
} from './owner-updates.mjs';

const update = (overrides = {}) => ({
  owner_update_id: 'update',
  category: 'feeding',
  occurred_at: '2026-08-30T10:00:00Z',
  recorded_at: '2026-08-30T10:01:00Z',
  note: 'Fed Raku.',
  ...overrides,
});

test('compact care updates keep the newest update for each non-measurement category', () => {
  const compact = selectCompactOwnerUpdates([
    update({ owner_update_id: 'feeding-old', occurred_at: '2026-08-30T09:00:00Z' }),
    update({ owner_update_id: 'feeding-new', occurred_at: '2026-08-30T11:00:00Z', note: 'Fed Raku again.' }),
    update({ owner_update_id: 'care', category: 'care', note: 'Changed 30% of the water.' }),
  ]);

  assert.deepEqual(compact.map((item) => item.owner_update_id), ['feeding-new', 'care']);
});

test('measurements are grouped by reading type while different readings coexist', () => {
  const compact = selectCompactOwnerUpdates([
    update({ owner_update_id: 'temperature-old', category: 'measurement', occurred_at: '2026-08-30T08:00:00Z', reading: { reading_type: 'water temperature', value: 27, unit: 'C' } }),
    update({ owner_update_id: 'temperature-new', category: 'measurement', occurred_at: '2026-08-30T12:00:00Z', reading: { reading_type: 'water_temperature', value: 28, unit: 'C' } }),
    update({ owner_update_id: 'ph', category: 'measurement', occurred_at: '2026-08-30T11:00:00Z', reading: { reading_type: 'pH', value: 7.2, unit: 'pH' } }),
  ]);

  assert.deepEqual(compact.map((item) => item.owner_update_id), ['temperature-new', 'ph']);
});

test('occurred time decides recency and recorded time deterministically breaks a tie', () => {
  const ordered = sortOwnerUpdates([
    update({ owner_update_id: 'earlier-event', occurred_at: '2026-08-30T10:00:00Z', recorded_at: '2026-08-30T13:00:00Z' }),
    update({ owner_update_id: 'later-event', occurred_at: '2026-08-30T11:00:00Z', recorded_at: '2026-08-30T11:01:00Z' }),
    update({ owner_update_id: 'tie-later-recorded', occurred_at: '2026-08-30T11:00:00Z', recorded_at: '2026-08-30T11:03:00Z' }),
  ]);

  assert.deepEqual(ordered.map((item) => item.owner_update_id), ['tie-later-recorded', 'later-event', 'earlier-event']);
});

test('the compact summary only operates on the bounded history supplied by the dashboard', () => {
  const loadedUpdates = Array.from({ length: 20 }, (_, index) => update({
    owner_update_id: `feeding-${index}`,
    occurred_at: `2026-08-30T${String(index % 10).padStart(2, '0')}:00:00Z`,
  }));

  assert.equal(sortOwnerUpdates(loadedUpdates).length, 20);
  assert.equal(selectCompactOwnerUpdates(loadedUpdates).length, 1);
});

test('source-less profiles need no special case to show their owner-provided updates', () => {
  const compact = selectCompactOwnerUpdates([
    update({ owner_update_id: 'source-less-note', category: 'note', note: 'Owner will be away until Sunday.' }),
  ]);

  assert.equal(compact[0].owner_update_id, 'source-less-note');
});

test('measurement summaries preserve canonical temperature formatting', () => {
  const summary = formatOwnerUpdateSummary(update({
    category: 'measurement',
    reading: { reading_type: 'water temperature', value: 33.5, unit: 'C' },
  }));

  assert.equal(summary.label, 'Water temperature');
  assert.equal(summary.detail, `33.5${String.fromCharCode(176)}C`);
});
