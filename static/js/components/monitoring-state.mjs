/** Small, data-only helpers shared by profile lists and the monitoring dashboard. */

export function hasMonitoringSource(profile) {
  return Boolean(
    profile
      && profile.source_type
      && profile.source_reference !== null
      && profile.source_reference !== undefined
  );
}

export function monitoringLifecycleState(profile) {
  if (!hasMonitoringSource(profile)) return 'source_not_connected';
  return profile.active === false ? 'paused' : 'active';
}

export function monitoringStatusText(profile) {
  const state = monitoringLifecycleState(profile);
  if (state === 'source_not_connected') return 'Monitoring source not connected';
  return state === 'active' ? 'Monitoring active' : 'Monitoring paused';
}

export function monitoringStatusClass(profile) {
  return monitoringLifecycleState(profile) === 'active' ? '' : 'is-idle';
}

export function monitoringDisplayPriority(profile) {
  const state = monitoringLifecycleState(profile);
  return state === 'active' ? 0 : state === 'paused' ? 1 : 2;
}

export function sourceDisplayLabel(profile) {
  if (!hasMonitoringSource(profile)) return 'Monitoring source not connected';
  if (profile.source_type === 'webcam') return 'Camera connected';
  return 'Video source connected';
}

export function profileSpeciesLabel(profile) {
  const species = profile && profile.expected_species;
  return typeof species === 'string' && species.trim() ? species.trim() : 'Species not recorded';
}

export function lifecycleActions(profile) {
  const state = monitoringLifecycleState(profile);
  if (state === 'source_not_connected') return ['connect'];
  if (state === 'paused') return ['start', 'change', 'disconnect'];
  return ['pause', 'change'];
}
