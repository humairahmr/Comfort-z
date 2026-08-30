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

test('local camera controls describe a snapshot and do not hardcode a camera index', async () => {
  const dashboard = await readFile(new URL('./dashboard.js', import.meta.url), 'utf8');

  assert.match(dashboard, /Preview camera/);
  assert.match(dashboard, /Snapshot only/);
  assert.doesNotMatch(dashboard, /camera_index:\s*1/);
});

test('owner-facing media controls use file pickers and never disclose storage paths', async () => {
  const [dashboard, onboarding, silhouettes] = await Promise.all([
    readFile(new URL('./dashboard.js', import.meta.url), 'utf8'),
    readFile(new URL('./onboarding.js', import.meta.url), 'utf8'),
    readFile(new URL('./silhouettes.js', import.meta.url), 'utf8'),
  ]);

  assert.match(onboarding, /Profile photo <em>Optional<\/em>/);
  assert.match(onboarding, /accept="image\/jpeg,image\/png,image\/webp"/);
  assert.match(dashboard, /Live camera/);
  assert.match(dashboard, /Video file/);
  assert.match(dashboard, /accept="video\/mp4,video\/webm,video\/quicktime"/);
  assert.match(dashboard, /uploadMonitoringVideo/);
  assert.match(silhouettes, /profile\.profile_photo_url/);
  assert.doesNotMatch(dashboard, /gs:\/\//);
  assert.doesNotMatch(onboarding, /gs:\/\//);
  assert.doesNotMatch(dashboard, /demo_videos|Raku\.mp4/i);
});

test('persisted profile photos render before silhouettes across dashboard collections', async () => {
  const [dashboard, overview, silhouettes] = await Promise.all([
    readFile(new URL('./dashboard.js', import.meta.url), 'utf8'),
    readFile(new URL('./overview.js', import.meta.url), 'utf8'),
    readFile(new URL('./silhouettes.js', import.meta.url), 'utf8'),
  ]);

  assert.match(silhouettes, /profile\.profile_photo_url/);
  assert.match(silhouettes, /if \(photo\)[\s\S]*<img/);
  assert.match(dashboard, /profileImageSource\(profile \|\| \{\}\)/);
  assert.match(overview, /profileImageSource\(profile\)/);
  assert.match(dashboard, /hasProfilePhoto \? '' : '<span class="hero-silhouette-caption/);
  assert.match(overview, /profileImageSource\(profile\) \? '' : '<span class="visual-disclaimer/);
});

test('dashboard async controls tolerate DOM replacement and location editing is explicit', async () => {
  const [dashboard, api] = await Promise.all([
    readFile(new URL('./dashboard.js', import.meta.url), 'utf8'),
    readFile(new URL('../api.js', import.meta.url), 'utf8'),
  ]);

  assert.match(dashboard, /runAsyncControl/);
  assert.doesNotMatch(dashboard, /finally\s*\{\s*event\.currentTarget\.disabled/);
  assert.match(dashboard, /Edit location/);
  assert.match(dashboard, /Outdoor weather context requires both coordinates/);
  assert.match(api, /updateMonitoringLocation/);
});
