import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import {
  hasMonitoringSource,
  lifecycleActions,
  monitoringDisplayPriority,
  monitoringLifecycleState,
  monitoringStatusText,
  profileSpeciesLabel,
} from './monitoring-state.mjs';

test('lifecycle states are derived from the real single-source profile fields', () => {
  const noSource = { animal_id: 'milo', source_reference: null, source_type: null, active: false };
  const paused = { animal_id: 'milo', source_reference: 1, source_type: 'webcam', active: false };
  const active = { animal_id: 'milo', source_reference: 1, source_type: 'webcam', active: true };

  assert.equal(hasMonitoringSource(noSource), false);
  assert.equal(monitoringLifecycleState(noSource), 'source_not_connected');
  assert.equal(monitoringStatusText(noSource), 'Monitoring source not connected');
  assert.deepEqual(lifecycleActions(noSource), ['connect']);
  assert.deepEqual(lifecycleActions(paused), ['start', 'change', 'disconnect']);
  assert.deepEqual(lifecycleActions(active), ['pause', 'change']);
  assert.deepEqual([noSource, paused, active].sort((a, b) => monitoringDisplayPriority(a) - monitoringDisplayPriority(b)), [active, paused, noSource]);
});

test('unknown species stays honest and never becomes a fake identified animal', () => {
  assert.equal(profileSpeciesLabel({ expected_species: null }), 'Species not recorded');
  assert.equal(profileSpeciesLabel({ expected_species: '  Domestic dog  ' }), 'Domestic dog');
});

test('frontend routes and source presentation contain no hardcoded demo-animal identity', async () => {
  const [index, api, dashboard, overview] = await Promise.all([
    readFile(new URL('../../index.html', import.meta.url), 'utf8'),
    readFile(new URL('../api.js', import.meta.url), 'utf8'),
    readFile(new URL('./dashboard.js', import.meta.url), 'utf8'),
    readFile(new URL('./overview.js', import.meta.url), 'utf8'),
  ]);

  assert.doesNotMatch(index, /#\/animals\/raku/i);
  assert.doesNotMatch(api, /animalId\.toLowerCase\(\) === 'raku'/);
  assert.doesNotMatch(dashboard, /\/demo-video\/raku\.mp4/);
  assert.doesNotMatch(overview, /Gendut architectural preview/i);
});
