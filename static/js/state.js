/**
 * Comfort-z UI State & Formatters
 */

export const state = {
  health: null,
  animals: [],
  selectedAnimalId: null,
  currentProfile: null,
  currentObservations: [],
  currentReports: [],
  loading: false,
  error: null,
};

/**
 * Format ISO timestamp into a human-readable string.
 */
export function formatTimestamp(isoString) {
  if (!isoString) return 'Not available';
  try {
    const d = new Date(isoString);
    if (isNaN(d.getTime())) return isoString;
    return d.toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  } catch (_) {
    return isoString;
  }
}

/**
 * Return CSS badge class and display label for observation/decision severity.
 */
export function getSeverityBadge(severity) {
  const s = (severity || '').toLowerCase();
  if (s === 'normal') {
    return { class: 'badge-normal', label: 'Normal' };
  }
  if (s === 'monitor') {
    return { class: 'badge-monitor', label: 'Monitor' };
  }
  if (s === 'potentially_concerning' || s === 'concerning') {
    return { class: 'badge-concerning', label: 'Potentially Concerning' };
  }
  return { class: 'badge-neutral', label: severity || 'Unknown' };
}

/**
 * Return human-readable label for trend enumeration.
 */
export function getTrendLabel(trend) {
  if (!trend) return 'Not established';
  const mapping = {
    'first_observation': 'First Observation (Baseline)',
    'insufficient_visibility': 'Insufficient Visibility',
    'unchanged': 'Unchanged',
    'improving': 'Improving',
    'worsening': 'Worsening',
    'suspicious_pattern_persisting': 'Pattern Persisting',
  };
  return mapping[trend] || trend.replace(/_/g, ' ');
}

/**
 * Format confidence float (0.0 to 1.0) into a percentage string.
 */
export function formatConfidence(conf) {
  if (typeof conf !== 'number' || isNaN(conf)) return 'Not available';
  return `${Math.round(conf * 100)}%`;
}

