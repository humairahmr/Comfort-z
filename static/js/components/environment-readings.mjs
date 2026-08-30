/** Bounded client-side selection for owner-entered enclosure measurements. */

const OWNER_MEASUREMENT_FRESHNESS_MS = 7 * 24 * 60 * 60 * 1000;

export function selectEnvironmentPanelReading({
  ownerUpdates = [],
  latestObservation = null,
  profile = null,
  now = Date.now(),
} = {}) {
  const ownerUpdate = selectLatestOwnerMeasurement(ownerUpdates);
  if (ownerUpdate) {
    return {
      source: 'owner_update',
      reading: ownerUpdate.reading,
      ownerUpdate,
      isFresh: isOwnerMeasurementFresh(ownerUpdate, now),
    };
  }

  const observationReading = firstValidReading(latestObservation?.direct_environment_readings);
  if (observationReading) return { source: 'observation', reading: observationReading, isFresh: null };

  const profileReading = firstValidReading(profile?.direct_environment_readings);
  if (profileReading) return { source: 'profile', reading: profileReading, isFresh: null };

  return null;
}

export function selectLatestOwnerMeasurement(ownerUpdates = []) {
  return ownerUpdates
    .filter((update) => String(update?.category || '').toLowerCase() === 'measurement' && isValidReading(update.reading))
    .filter((update) => timestampMilliseconds(update.occurred_at) !== null)
    .sort((left, right) => (
      timestampMilliseconds(right.occurred_at) - timestampMilliseconds(left.occurred_at)
      || timestampMilliseconds(right.recorded_at) - timestampMilliseconds(left.recorded_at)
      || String(right.owner_update_id || '').localeCompare(String(left.owner_update_id || ''))
    ))[0] || null;
}

export function shouldSuppressMissingReadingRequest(request, enclosureReading) {
  if (!request || enclosureReading?.source !== 'owner_update' || !enclosureReading.isFresh) return false;
  return /temperature/i.test(request) && /temperature/i.test(enclosureReading.reading.reading_type || '');
}

export function formatDirectReadingValue(reading) {
  const value = String(reading?.value ?? '').trim();
  const rawUnit = String(reading?.unit || '').trim();
  const degree = String.fromCharCode(176);
  const unit = rawUnit.replace(new RegExp(`^${degree}+`), degree).replace(/\s+/g, ' ').trim();
  const isTemperature = /temperature/i.test(reading?.reading_type || '');
  const temperatureUnit = unit
    .toLowerCase()
    .split(degree)
    .join('')
    .replace(/\s+/g, ' ')
    .trim();
  const canonicalTemperatureUnit = !isTemperature ? null
    : ['c', 'celsius', 'degree c', 'degrees c', 'degree celsius', 'degrees celsius'].includes(temperatureUnit)
      ? 'C'
      : ['f', 'fahrenheit', 'degree f', 'degrees f', 'degree fahrenheit', 'degrees fahrenheit'].includes(temperatureUnit)
        ? 'F'
        : null;
  if (canonicalTemperatureUnit) return `${value}${degree}${canonicalTemperatureUnit}`;
  return unit ? `${value} ${unit}` : value;
}

export function formatReadingType(readingType) {
  const value = String(readingType || 'Direct reading').replace(/_/g, ' ').trim();
  return value ? `${value.charAt(0).toUpperCase()}${value.slice(1).toLowerCase()}` : 'Direct reading';
}

export function formatOwnerReportedTimestamp(value) {
  if (!value) return 'Not available';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  const separator = String.fromCharCode(183);
  return `${separator} ${date.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })}`;
}

export function formatOwnerMeasurementAge(ownerUpdate, now = Date.now()) {
  const occurredAt = timestampMilliseconds(ownerUpdate?.occurred_at);
  const currentTime = now instanceof Date ? now.getTime() : Number(now);
  if (occurredAt === null || !Number.isFinite(currentTime)) return 'an unknown time ago';
  const minutes = Math.max(0, Math.floor((currentTime - occurredAt) / 60_000));
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? '' : 's'} ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? '' : 's'} ago`;
  const days = Math.floor(hours / 24);
  return `${days} day${days === 1 ? '' : 's'} ago`;
}

function isOwnerMeasurementFresh(ownerUpdate, now) {
  const occurredAt = timestampMilliseconds(ownerUpdate?.occurred_at);
  const currentTime = now instanceof Date ? now.getTime() : Number(now);
  return occurredAt !== null && Number.isFinite(currentTime)
    && occurredAt >= currentTime - OWNER_MEASUREMENT_FRESHNESS_MS;
}

function firstValidReading(readings) {
  return Array.isArray(readings) ? readings.find(isValidReading) || null : null;
}

function isValidReading(reading) {
  return Boolean(
    reading
    && typeof reading.reading_type === 'string'
    && reading.reading_type.trim()
    && Number.isFinite(Number(reading.value))
    && typeof reading.unit === 'string'
    && reading.unit.trim()
  );
}

function timestampMilliseconds(value) {
  const milliseconds = Date.parse(value || '');
  return Number.isFinite(milliseconds) ? milliseconds : null;
}
