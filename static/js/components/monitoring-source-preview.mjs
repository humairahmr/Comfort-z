export function supportsMonitoringVideoPreview(profile = {}) {
  return profile.source_type === 'video' && profile.source_reference != null;
}

export function monitoringSourcePreviewUrl(animalId) {
  return `/animals/${encodeURIComponent(animalId)}/monitoring-source-preview`;
}

export function initializeMonitoringVideoPreview({ video, fallback, context, url }) {
  const showFallback = () => {
    video.hidden = true;
    context.hidden = true;
    fallback.hidden = false;
  };
  video.addEventListener('error', showFallback, { once: true });
  video.src = url;
  video.load();
}
