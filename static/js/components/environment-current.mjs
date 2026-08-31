export function hasAmbientCoordinates(profile = {}) {
  return profile.latitude != null
    && profile.longitude != null
    && Number.isFinite(Number(profile.latitude))
    && Number.isFinite(Number(profile.longitude));
}

export async function loadCurrentEnvironment(profile, fetchCurrentEnvironment) {
  if (!hasAmbientCoordinates(profile)) {
    return { status: 'not_configured', context: null };
  }

  try {
    const context = await fetchCurrentEnvironment({
      latitude: Number(profile.latitude),
      longitude: Number(profile.longitude),
      locationName: profile.location_name || null,
    });
    return { status: 'available', context };
  } catch (_error) {
    return { status: 'unavailable', context: null };
  }
}

export function createAmbientWeatherView({ profile = {}, currentEnvironment, latestObservation }) {
  const configured = hasAmbientCoordinates(profile);
  const currentContext = currentEnvironment?.status === 'available'
    ? currentEnvironment.context
    : null;
  const historicalContext = !configured ? latestObservation?.environment_context : null;
  const context = currentContext || historicalContext || null;
  const locationName = context?.location_name || profile.location_name || 'Location not recorded';

  if (!context) {
    return {
      status: configured ? 'unavailable' : 'not_configured',
      locationName,
      temperature: configured ? 'Temporarily unavailable' : 'Not recorded',
      humidity: null,
      condition: null,
      provider: null,
      observedAt: null,
      historical: false,
    };
  }

  return {
    status: currentContext ? 'available' : 'historical',
    locationName,
    temperature: formatCelsius(context.outdoor_temperature_c),
    humidity: formatHumidity(context.outdoor_humidity_percent),
    condition: context.weather_condition || null,
    provider: context.provider || null,
    observedAt: context.observed_at || null,
    historical: !currentContext,
  };
}

export function formatCelsius(value) {
  return value == null || !Number.isFinite(Number(value)) ? null : `${formatNumber(value)}°C`;
}

export function formatHumidity(value) {
  return value == null || !Number.isFinite(Number(value)) ? null : `${formatNumber(value)}%`;
}

function formatNumber(value) {
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(Number(value));
}
