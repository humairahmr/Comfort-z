import assert from 'node:assert/strict';
import test from 'node:test';

import { populateCoordinateFields, requestBrowserLocation } from './geolocation.mjs';

function fakeGeolocation({ position, error }) {
  return {
    getCurrentPosition(onSuccess, onError) {
      if (error) onError(error);
      else onSuccess(position);
    },
  };
}

test('explicit location request populates the existing form with rounded coordinates', async () => {
  const result = await requestBrowserLocation(fakeGeolocation({
    position: { coords: { latitude: 1.55331234, longitude: 110.35924567 } },
  }));
  const form = { elements: { latitude: { value: '' }, longitude: { value: '' } } };
  populateCoordinateFields(form, result);

  assert.deepEqual(result, { latitude: 1.553312, longitude: 110.359246 });
  assert.equal(form.elements.latitude.value, '1.553312');
  assert.equal(form.elements.longitude.value, '110.359246');
});

test('permission denial uses the owner-facing manual-entry recovery', async () => {
  await assert.rejects(
    requestBrowserLocation(fakeGeolocation({ error: { code: 1 } })),
    { message: 'Location permission was denied. You can enter it manually.' },
  );
});

test('unavailable and timeout errors remain specific and recoverable', async () => {
  await assert.rejects(
    requestBrowserLocation(fakeGeolocation({ error: { code: 2 } })),
    { message: 'Your location could not be determined. You can enter it manually.' },
  );
  await assert.rejects(
    requestBrowserLocation(fakeGeolocation({ error: { code: 3 } })),
    { message: 'Location request timed out. You can enter it manually.' },
  );
});

test('unsupported browsers retain manual location entry', async () => {
  await assert.rejects(
    requestBrowserLocation(null),
    { message: 'Location access is not available in this browser. You can enter it manually.' },
  );
});
