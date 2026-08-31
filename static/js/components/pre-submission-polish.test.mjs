import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import {
  createAmbientWeatherView,
  loadCurrentEnvironment,
} from './environment-current.mjs';

test('current ambient weather is loaded independently from stored observations', async () => {
  let request;
  const state = await loadCurrentEnvironment(
    { location_name: 'Kuching', latitude: 1.5533, longitude: 110.3592 },
    async (value) => {
      request = value;
      return {
        provider: 'Open-Meteo',
        location_name: 'Kuching',
        outdoor_temperature_c: 33.6,
        outdoor_humidity_percent: 68,
        weather_condition: 'partly cloudy',
        observed_at: '2026-08-31T12:00:00Z',
      };
    },
  );
  const view = createAmbientWeatherView({
    profile: { location_name: 'Kuching', latitude: 1.5533, longitude: 110.3592 },
    currentEnvironment: state,
    latestObservation: {
      environment_context: { outdoor_temperature_c: 21, outdoor_humidity_percent: 40 },
    },
  });

  assert.deepEqual(request, {
    latitude: 1.5533,
    longitude: 110.3592,
    locationName: 'Kuching',
  });
  assert.equal(view.temperature, `33.6${String.fromCharCode(176)}C`);
  assert.equal(view.humidity, '68%');
  assert.equal(view.status, 'available');
});

test('ambient failure is contained and direct enclosure readings remain a separate path', async () => {
  const state = await loadCurrentEnvironment(
    { latitude: 1, longitude: 2 },
    async () => { throw new Error('offline'); },
  );
  const view = createAmbientWeatherView({
    profile: {
      latitude: 1,
      longitude: 2,
      direct_environment_readings: [{ reading_type: 'water_temperature', value: 27, unit: 'C' }],
    },
    currentEnvironment: state,
    latestObservation: null,
  });

  assert.equal(view.status, 'unavailable');
  assert.equal(view.temperature, 'Temporarily unavailable');

  const dashboard = await readFile(new URL('./dashboard.js', import.meta.url), 'utf8');
  assert.match(dashboard, /createAmbientWeatherView/);
  assert.match(dashboard, /selectEnvironmentPanelReading/);
  assert.match(dashboard, /Ambient \/ Outdoor Weather/);
  assert.match(dashboard, /Owner-Reported Enclosure Reading/);
});

test('profile photos fill hero media while silhouette fallback markup remains conditional', async () => {
  const [css, dashboard, overview] = await Promise.all([
    readFile(new URL('../../css/components.css', import.meta.url), 'utf8'),
    readFile(new URL('./dashboard.js', import.meta.url), 'utf8'),
    readFile(new URL('./overview.js', import.meta.url), 'utf8'),
  ]);

  assert.match(css, /has-profile-photo \.hero-profile-visual\.animal-photo[^}]*width:\s*100%[^}]*height:\s*100%/s);
  assert.match(css, /has-profile-photo \.animal-hero-visual\.animal-photo[^}]*width:\s*100%[^}]*height:\s*100%/s);
  assert.match(css, /\.animal-card-silhouette\.animal-photo[^}]*width:\s*100%[^}]*height:\s*100%/s);
  assert.match(dashboard, /hero-portrait-frame\$\{hasProfilePhoto \? ' has-profile-photo' : ''\}/);
  assert.match(dashboard, /hasProfilePhoto \? '' : '<span class="hero-silhouette-caption/);
  assert.match(overview, /animal-hero-visual-wrap\$\{profileImageSource\(profile\) \? ' has-profile-photo' : ''\}/);
  assert.match(overview, /profileImageSource\(profile\) \? '' : '<span class="visual-disclaimer/);
});

test('geolocation is bound to the explicit owner control and never page initialization', async () => {
  const [dashboard, app] = await Promise.all([
    readFile(new URL('./dashboard.js', import.meta.url), 'utf8'),
    readFile(new URL('../app.js', import.meta.url), 'utf8'),
  ]);

  assert.match(dashboard, /data-use-location/);
  assert.match(dashboard, /useLocationButton\.addEventListener\('click'/);
  assert.doesNotMatch(app, /requestBrowserLocation|getCurrentPosition/);
});
