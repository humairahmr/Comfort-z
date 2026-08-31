const LOCATION_ERRORS = {
  1: 'Location permission was denied. You can enter it manually.',
  2: 'Your location could not be determined. You can enter it manually.',
  3: 'Location request timed out. You can enter it manually.',
};

const UNSUPPORTED_MESSAGE = 'Location access is not available in this browser. You can enter it manually.';

export function requestBrowserLocation(geolocation = globalThis.navigator?.geolocation) {
  if (!geolocation || typeof geolocation.getCurrentPosition !== 'function') {
    return Promise.reject(new Error(UNSUPPORTED_MESSAGE));
  }

  return new Promise((resolve, reject) => {
    geolocation.getCurrentPosition(
      (position) => resolve({
        latitude: roundCoordinate(position.coords.latitude),
        longitude: roundCoordinate(position.coords.longitude),
      }),
      (error) => reject(new Error(LOCATION_ERRORS[error?.code] || LOCATION_ERRORS[2])),
      { enableHighAccuracy: false, timeout: 8_000, maximumAge: 300_000 },
    );
  });
}

export function populateCoordinateFields(form, coordinates) {
  form.elements.latitude.value = String(coordinates.latitude);
  form.elements.longitude.value = String(coordinates.longitude);
}

function roundCoordinate(value) {
  return Number(Number(value).toFixed(6));
}
