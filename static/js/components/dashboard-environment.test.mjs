import assert from 'node:assert/strict';
import test from 'node:test';

import {
  formatDirectReadingValue,
  formatOwnerMeasurementAge,
  formatOwnerReportedTimestamp,
  formatReadingType,
  selectEnvironmentPanelReading,
  shouldSuppressMissingReadingRequest,
} from './environment-readings.mjs';

const NOW = Date.parse('2026-08-30T16:00:00Z');
const waterTemperature = (overrides = {}) => ({
  owner_update_id: 'temperature-update',
  category: 'measurement',
  occurred_at: '2026-08-30T15:55:00Z',
  recorded_at: '2026-08-30T15:56:00Z',
  reading: { reading_type: 'water temperature', value: 27, unit: 'C' },
  ...overrides,
});

test('a new owner measurement takes precedence over a stale observation snapshot', () => {
  const selected = selectEnvironmentPanelReading({
    ownerUpdates: [waterTemperature()],
    latestObservation: { direct_environment_readings: [{ reading_type: 'water temperature', value: 25, unit: 'C' }] },
    profile: { direct_environment_readings: [{ reading_type: 'water temperature', value: 25, unit: 'C' }] },
    now: NOW,
  });

  assert.equal(selected.source, 'owner_update');
  assert.equal(selected.reading.value, 27);
  assert.equal(selected.isFresh, true);
});

test('an empty observation reading array does not block an owner measurement', () => {
  const selected = selectEnvironmentPanelReading({
    ownerUpdates: [waterTemperature()],
    latestObservation: { direct_environment_readings: [] },
    profile: { direct_environment_readings: [{ reading_type: 'water temperature', value: 25, unit: 'C' }] },
    now: NOW,
  });

  assert.equal(selected.source, 'owner_update');
  assert.equal(selected.reading.value, 27);
});

test('the most recent occurrence wins, then recorded time deterministically breaks a tie', () => {
  const selected = selectEnvironmentPanelReading({
    ownerUpdates: [
      waterTemperature({ owner_update_id: 'older', occurred_at: '2026-08-30T14:00:00Z' }),
      waterTemperature({ owner_update_id: 'tie-earlier', occurred_at: '2026-08-30T15:55:00Z', recorded_at: '2026-08-30T15:56:00Z' }),
      waterTemperature({ owner_update_id: 'tie-later', occurred_at: '2026-08-30T15:55:00Z', recorded_at: '2026-08-30T15:57:00Z' }),
    ],
    now: NOW,
  });

  assert.equal(selected.ownerUpdate.owner_update_id, 'tie-later');
});

test('only a fresh matching temperature measurement suppresses an old temperature request', () => {
  const selected = selectEnvironmentPanelReading({ ownerUpdates: [waterTemperature()], now: NOW });

  assert.equal(
    shouldSuppressMissingReadingRequest('Ask the owner for a direct temperature reading.', selected),
    true,
  );
  assert.equal(
    shouldSuppressMissingReadingRequest('Ask the owner for a direct humidity reading.', selected),
    false,
  );
});

test('an older measurement remains historical and does not suppress a fresh-reading advisory', () => {
  const selected = selectEnvironmentPanelReading({
    ownerUpdates: [waterTemperature({ occurred_at: '2026-08-22T15:55:00Z' })],
    now: NOW,
  });

  assert.equal(selected.source, 'owner_update');
  assert.equal(selected.isFresh, false);
  assert.equal(
    shouldSuppressMissingReadingRequest('Ask the owner for a direct temperature reading.', selected),
    false,
  );
});

test('legacy readings remain the fallback for a source-less profile with no owner measurement', () => {
  const selected = selectEnvironmentPanelReading({
    ownerUpdates: [{ category: 'feeding', note: 'Fed Raku.' }],
    latestObservation: { direct_environment_readings: [] },
    profile: {
      source_reference: null,
      direct_environment_readings: [{ reading_type: 'enclosure humidity', value: 60, unit: '%' }],
    },
    now: NOW,
  });

  assert.equal(selected.source, 'profile');
  assert.equal(selected.reading.value, 60);
});

test('a source-less profile can still display an owner-provided measurement', () => {
  const selected = selectEnvironmentPanelReading({
    ownerUpdates: [waterTemperature()],
    profile: { source_reference: null, direct_environment_readings: [] },
    now: NOW,
  });

  assert.equal(selected.source, 'owner_update');
});

test('dashboard renders canonical Celsius and Fahrenheit without changing non-temperature units', () => {
  const degree = String.fromCharCode(176);
  const temperature = (unit) => formatDirectReadingValue({ reading_type: 'water temperature', value: 27, unit });

  ['C', `${degree}C`, 'Celsius', `${degree} Celsius`, `${degree}${degree}C`]
    .forEach((unit) => assert.equal(temperature(unit), `27${degree}C`));
  assert.equal(
    formatDirectReadingValue({ reading_type: 'water temperature', value: 80, unit: 'Fahrenheit' }),
    `80${degree}F`,
  );
  assert.equal(
    formatDirectReadingValue({ reading_type: 'enclosure humidity', value: 60, unit: 'degrees' }),
    '60 degrees',
  );
});

test('owner timestamp omits seconds and the context age is human-friendly', () => {
  const timestamp = formatOwnerReportedTimestamp('2026-08-30T15:55:00Z');

  assert.match(timestamp, /^. .*:55 (AM|PM)$/i);
  assert.doesNotMatch(timestamp, /:55:00/);
  assert.equal(formatOwnerMeasurementAge(waterTemperature(), NOW), '5 minutes ago');
  assert.equal(formatReadingType('water_temperature'), 'Water temperature');
});
