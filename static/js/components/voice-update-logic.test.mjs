import assert from 'node:assert/strict';
import test from 'node:test';

import {
  evaluateVoiceAutoSave,
  persistVoiceAutoSaveBatch,
  refreshSavedVoiceUpdates,
} from './voice-update-logic.mjs';

const measurement = (overrides = {}) => ({
  category: 'measurement',
  occurred_at: '2026-08-30T12:00:00Z',
  reading: { reading_type: 'water temperature', value: 27, unit: 'C' },
  unit_confirmation_required: false,
  ...overrides,
});

const feeding = (overrides = {}) => ({
  category: 'feeding',
  occurred_at: '2026-08-30T12:00:00Z',
  note: 'Fed Raku.',
  ...overrides,
});

test('one complete canonical draft qualifies for auto-save', () => {
  const result = evaluateVoiceAutoSave({ drafts: [measurement()] });

  assert.equal(result.eligible, true);
  assert.deepEqual(result.payloads[0].reading.unit, 'C');
  assert.equal(result.payloads[0].input_method, 'voice');
});

test('an unresolved temperature, missing occurrence, warning, or malformed measurement requires review', () => {
  [
    measurement({ reading: { reading_type: 'water temperature', value: 27, unit: 'degrees' }, unit_confirmation_required: true }),
    feeding({ occurred_at: null }),
    feeding({ review_warning: 'Choose the time this happened.' }),
    measurement({ reading: { reading_type: 'water temperature', value: '', unit: 'C' } }),
  ].forEach((draft) => assert.equal(evaluateVoiceAutoSave({ drafts: [draft] }).eligible, false));
});

test('two clear facts qualify as one auto-save batch, while one unsafe fact blocks all of them', () => {
  const safe = evaluateVoiceAutoSave({ drafts: [measurement(), feeding()] });
  const unsafe = evaluateVoiceAutoSave({
    drafts: [measurement(), feeding({ occurred_at: null })],
  });

  assert.equal(safe.eligible, true);
  assert.equal(safe.payloads.length, 2);
  assert.equal(unsafe.eligible, false);
  assert.deepEqual(unsafe.payloads, []);
});

test('auto-save persists sequentially and refreshes owner updates once after complete success', async () => {
  const calls = [];
  const outcome = await persistVoiceAutoSaveBatch({
    animalId: 'raku',
    payloads: evaluateVoiceAutoSave({ drafts: [measurement(), feeding()] }).payloads,
    createOwnerUpdate: async (_animalId, payload) => {
      calls.push(payload.category);
      return { owner_update_id: `saved-${calls.length}` };
    },
  });
  const refreshed = [];
  await refreshSavedVoiceUpdates(outcome.saved, async (ownerUpdateId) => refreshed.push(ownerUpdateId));

  assert.equal(outcome.complete, true);
  assert.deepEqual(calls, ['measurement', 'feeding']);
  assert.deepEqual(refreshed, ['saved-2']);
});

test('a partial sequential failure does not resubmit already saved drafts', async () => {
  const calls = [];
  const outcome = await persistVoiceAutoSaveBatch({
    animalId: 'raku',
    payloads: evaluateVoiceAutoSave({ drafts: [measurement(), feeding(), feeding({ note: 'Fed Raku again.' })] }).payloads,
    createOwnerUpdate: async (_animalId, payload) => {
      calls.push(payload.note || payload.reading.reading_type);
      if (calls.length === 2) throw new Error('Temporary network failure');
      return { owner_update_id: `saved-${calls.length}` };
    },
  });

  assert.equal(outcome.complete, false);
  assert.equal(outcome.saved.length, 1);
  assert.equal(outcome.unsaved.length, 2);
  assert.deepEqual(calls, ['water temperature', 'Fed Raku.']);
});
