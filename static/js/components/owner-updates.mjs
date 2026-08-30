/** Bounded presentation helpers for persisted owner-provided care history. */

import { formatDirectReadingValue, formatReadingType } from './environment-readings.mjs';

export function selectCompactOwnerUpdates(ownerUpdates = []) {
  const newestByContext = new Map();

  sortOwnerUpdates(ownerUpdates).forEach((update) => {
    const key = ownerUpdateContextKey(update);
    if (key && !newestByContext.has(key)) newestByContext.set(key, update);
  });

  return sortOwnerUpdates([...newestByContext.values()]);
}

export function sortOwnerUpdates(ownerUpdates = []) {
  return [...(Array.isArray(ownerUpdates) ? ownerUpdates : [])].sort((left, right) => (
    timestampMilliseconds(right?.occurred_at) - timestampMilliseconds(left?.occurred_at)
    || timestampMilliseconds(right?.recorded_at) - timestampMilliseconds(left?.recorded_at)
    || String(right?.owner_update_id || '').localeCompare(String(left?.owner_update_id || ''))
  ));
}

export function formatOwnerUpdateSummary(update) {
  const reading = update?.reading;
  if (reading && update?.category === 'measurement') {
    return {
      label: formatReadingType(reading.reading_type),
      detail: formatDirectReadingValue(reading),
    };
  }
  return {
    label: ownerUpdateLabel(update?.category),
    detail: String(update?.note || 'Owner-provided update.'),
  };
}

export function ownerUpdateLabel(category) {
  const labels = {
    measurement: 'Direct reading',
    feeding: 'Feeding',
    care: 'Care',
    appetite: 'Appetite',
    behavior: 'Behaviour',
    availability: 'Availability',
    note: 'Owner note',
  };
  return labels[category] || 'Owner update';
}

function ownerUpdateContextKey(update) {
  const category = String(update?.category || '').trim().toLowerCase();
  if (!category) return null;
  if (category !== 'measurement') return `category:${category}`;
  const readingType = String(update?.reading?.reading_type || '')
    .trim()
    .toLowerCase()
    .replace(/_/g, ' ')
    .replace(/\s+/g, ' ');
  return readingType ? `measurement:${readingType}` : null;
}

function timestampMilliseconds(value) {
  const timestamp = Date.parse(value || '');
  return Number.isFinite(timestamp) ? timestamp : -Infinity;
}
