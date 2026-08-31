/**
 * Animal Monitoring Dashboard Component
 * Renders the commanding editorial console with the Animal Identity Hero
 * and dark Observation Stage as visual protagonist.
 */

import { api } from '../api.js';
import {
  formatTimestamp,
  getSeverityBadge,
  getTrendLabel,
  formatConfidence,
} from '../state.js';
import { profileImageSource, renderAnimalVisual } from './silhouettes.js';
import { createCameraPreviewController, createCameraPreviewState } from './camera-preview.mjs';
import { runAsyncControl } from './async-action.mjs';
import { createAmbientWeatherView } from './environment-current.mjs';
import { populateCoordinateFields, requestBrowserLocation } from './geolocation.mjs';
import { createVoiceUpdatePanel } from './voice-update.js';
import {
  formatDirectReadingValue,
  formatOwnerMeasurementAge,
  formatOwnerReportedTimestamp,
  formatReadingType,
  selectEnvironmentPanelReading,
  shouldSuppressMissingReadingRequest,
} from './environment-readings.mjs';
import {
  formatOwnerUpdateSummary,
  selectCompactOwnerUpdates,
  sortOwnerUpdates,
} from './owner-updates.mjs';
import {
  hasMonitoringSource,
  lifecycleActions,
  monitoringLifecycleState,
  monitoringStatusText,
  profileSpeciesLabel,
  sourceDisplayLabel,
  sourceSamplingDetail,
} from './monitoring-state.mjs';

export function renderDashboard(
  animalId,
  profile,
  observations,
  reports,
  ownerUpdates,
  navigate,
  onRefresh,
  onOwnerUpdatesRefresh,
  currentEnvironment,
) {
  const container = document.createElement('div');
  container.className = 'dashboard-container';

  const name = (profile && profile.animal_name) || (observations[0] && observations[0].animal_name) || animalId;
  const latestObs = observations && observations.length > 0 ? observations[0] : null;

  // 1. Breadcrumb Navigation
  const breadcrumb = document.createElement('nav');
  breadcrumb.className = 'nav-breadcrumb';
  breadcrumb.setAttribute('aria-label', 'Breadcrumb');
  breadcrumb.innerHTML = `
    <a href="#/overview" id="back-to-overview">← Monitored Animals</a>
    <span aria-hidden="true">/</span>
    <span aria-current="page">${escapeHtml(name)}</span>
  `;
  breadcrumb.querySelector('#back-to-overview').addEventListener('click', (e) => {
    e.preventDefault();
    navigate('#/overview');
  });
  container.appendChild(breadcrumb);

  // 2. Editorial Animal Profile Hero (The Identity Anchor)
  container.appendChild(createAnimalHero(animalId, profile, latestObs));

  container.appendChild(createMonitoringLifecycleControls(animalId, profile, onRefresh));

  // Owner-provided context is intentionally separate from visual observations.
  container.appendChild(createOwnerUpdatesModule(animalId, ownerUpdates, onOwnerUpdatesRefresh));

  // 3. Editorial Console Workspace
  const consoleLayout = document.createElement('div');
  consoleLayout.className = 'console-dashboard';

  // Section 1: The Unified Observation Stage (Dark Primary Visual Anchor - Preserved)
  consoleLayout.appendChild(createObservationStage(animalId, profile, latestObs, onRefresh));

  // Section 2: Full-Width Dual-Context Environmental Reasoning Ribbon (No Boxy Cards)
  consoleLayout.appendChild(createTelemetryRibbon(profile, latestObs, ownerUpdates, currentEnvironment));

  // Section 3: Longitudinal Intelligence & Archives (Open, Asymmetric Architecture)
  const intelLayout = document.createElement('div');
  intelLayout.className = 'intelligence-layout';

  // Left Intelligence Column: Longitudinal Trend & Grounded Research
  const intelLeft = document.createElement('div');
  intelLeft.className = 'intel-col';
  intelLeft.appendChild(createTrendModule(latestObs));
  intelLeft.appendChild(createResearchModule(latestObs));
  intelLayout.appendChild(intelLeft);

  // Right Archives Column: 24h Daily Reports & Chronological Log
  const intelRight = document.createElement('div');
  intelRight.className = 'intel-col';
  intelRight.appendChild(createReportsModule(animalId, profile, reports, onRefresh));
  intelRight.appendChild(createTimelineModule(observations));
  intelLayout.appendChild(intelRight);

  consoleLayout.appendChild(intelLayout);

  // Section 4: Compact Footer Diagnostics Ribbon
  consoleLayout.appendChild(createDiagnosticsRibbon(profile, latestObs));

  container.appendChild(consoleLayout);
  return container;
}

function createOwnerUpdatesModule(animalId, ownerUpdates, onOwnerUpdatesRefresh) {
  const section = document.createElement('section');
  section.className = 'owner-updates-module';
  section.setAttribute('aria-label', 'Owner-provided care updates');

  const updates = Array.isArray(ownerUpdates) ? ownerUpdates : [];
  const compactUpdates = selectCompactOwnerUpdates(updates);
  const chronologicalUpdates = sortOwnerUpdates(updates);
  const hasAdditionalHistory = chronologicalUpdates.length > compactUpdates.length;
  section.innerHTML = `
    <div class="owner-updates-header">
      <div>
        <h2>Care updates</h2>
        <p>Owner-provided information, kept separate from visual observations.</p>
      </div>
      <div class="owner-update-entry-actions">
        <button type="button" class="btn btn-secondary owner-update-toggle" aria-expanded="false">Add update</button>
        <button type="button" class="btn btn-secondary owner-update-voice-trigger">
          <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="2" width="6" height="12" rx="3"></rect><path d="M5 11a7 7 0 0 0 14 0M12 18v4M8 22h8"></path></svg>
          Voice update
        </button>
      </div>
    </div>
    <form class="owner-update-form" hidden novalidate>
      <div class="owner-update-fields">
        <label class="owner-update-field">
          <span>Type</span>
          <select name="category">
            <option value="feeding">Feeding</option>
            <option value="care">Care</option>
            <option value="appetite">Appetite</option>
            <option value="behavior">Behaviour note</option>
            <option value="availability">Availability</option>
            <option value="note">General note</option>
            <option value="measurement">Direct reading</option>
          </select>
        </label>
        <label class="owner-update-field">
          <span>When it happened</span>
          <input name="occurred_at" type="datetime-local" required value="${localDateTimeValue()}">
        </label>
      </div>
      <label class="owner-update-field owner-update-note-field">
        <span>Update</span>
        <textarea name="note" maxlength="500" placeholder="For example, fed at 8 PM or changed about 30% of the water."></textarea>
      </label>
      <div class="owner-update-reading-fields" hidden>
        <label class="owner-update-field">
          <span>Reading type</span>
          <input name="reading_type" maxlength="100" placeholder="For example, water temperature">
        </label>
        <label class="owner-update-field">
          <span>Value</span>
          <input name="reading_value" type="number" step="any" inputmode="decimal" placeholder="27">
        </label>
        <label class="owner-update-field">
          <span>Unit</span>
          <input name="reading_unit" maxlength="32" placeholder="°C">
        </label>
      </div>
      <div class="owner-update-actions">
        <span class="owner-update-message" role="status" aria-live="polite"></span>
        <div class="owner-update-action-buttons">
          <button type="button" class="btn btn-secondary owner-update-cancel">Cancel</button>
          <button type="button" class="btn btn-secondary owner-update-refresh" hidden>Refresh updates</button>
          <button type="submit" class="btn btn-primary">Save update</button>
        </div>
      </div>
    </form>
    <div class="owner-update-list">
      ${compactUpdates.length === 0
        ? '<p class="empty-inline">No care updates recorded yet.</p>'
        : compactUpdates.map(renderOwnerUpdate).join('')}
    </div>
    ${hasAdditionalHistory ? `
      <div class="owner-update-history" hidden>
        <div class="owner-update-history-list">${chronologicalUpdates.map(renderOwnerUpdate).join('')}</div>
      </div>
      <button type="button" class="owner-update-history-toggle btn btn-secondary" aria-expanded="false">
        View update history (${chronologicalUpdates.length} loaded)
      </button>
    ` : ''}
  `;

  const toggle = section.querySelector('.owner-update-toggle');
  const form = section.querySelector('.owner-update-form');
  const category = form.elements.category;
  const noteField = section.querySelector('.owner-update-note-field');
  const readingFields = section.querySelector('.owner-update-reading-fields');
  const message = section.querySelector('.owner-update-message');
  const submit = form.querySelector('[type="submit"]');
  const cancel = section.querySelector('.owner-update-cancel');
  const refresh = section.querySelector('.owner-update-refresh');
  const voiceTrigger = section.querySelector('.owner-update-voice-trigger');
  const history = section.querySelector('.owner-update-history');
  const historyToggle = section.querySelector('.owner-update-history-toggle');

  const updateFieldVisibility = () => {
    const measurement = category.value === 'measurement';
    noteField.hidden = measurement;
    readingFields.hidden = !measurement;
    form.elements.note.required = !measurement;
    form.elements.reading_type.required = measurement;
    form.elements.reading_value.required = measurement;
    form.elements.reading_unit.required = measurement;
  };

  let saving = false;
  let savedButRefreshFailed = false;
  let savedOwnerUpdateId = null;

  const setFormOpen = (open, { reset = false } = {}) => {
    form.hidden = !open;
    toggle.setAttribute('aria-expanded', String(open));
    toggle.textContent = open ? 'Close update' : 'Add update';
    if (reset) {
      form.reset();
      updateFieldVisibility();
      if (!savedButRefreshFailed) {
        message.textContent = '';
        delete message.dataset.state;
        refresh.hidden = true;
      }
    }
    if (open) form.elements.category.focus();
  };

  toggle.addEventListener('click', () => {
    voicePanel.close();
    setFormOpen(form.hidden, { reset: !form.hidden });
  });
  cancel.addEventListener('click', () => setFormOpen(false, { reset: true }));
  category.addEventListener('change', updateFieldVisibility);
  updateFieldVisibility();

  if (history && historyToggle) {
    historyToggle.addEventListener('click', () => {
      const opening = history.hidden;
      history.hidden = !opening;
      historyToggle.setAttribute('aria-expanded', String(opening));
      historyToggle.textContent = opening ? 'Hide history' : `View update history (${chronologicalUpdates.length} loaded)`;
    });
  }

  const refreshSavedUpdate = async (savedOwnerUpdateId = null) => {
    if (typeof onOwnerUpdatesRefresh !== 'function') {
      throw new Error('Update was saved, but Care updates cannot refresh on this page.');
    }
    await onOwnerUpdatesRefresh(savedOwnerUpdateId);
    savedButRefreshFailed = false;
    setFormOpen(false, { reset: true });
  };

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (saving || savedButRefreshFailed) return;
    const isMeasurement = category.value === 'measurement';
    const occurredAt = form.elements.occurred_at.value;
    const note = form.elements.note.value.trim();
    const readingType = form.elements.reading_type.value.trim();
    const readingValueText = form.elements.reading_value.value.trim();
    const readingValue = Number(readingValueText);
    const readingUnit = form.elements.reading_unit.value.trim();

    if (!occurredAt || (!isMeasurement && !note) || (
      isMeasurement && (!readingType || !readingValueText || !Number.isFinite(readingValue) || !readingUnit)
    )) {
      message.textContent = isMeasurement
        ? 'Add a reading type, numeric value, and unit.'
        : 'Add a concise update before saving.';
      message.dataset.state = 'error';
      return;
    }

    const payload = {
      category: category.value,
      occurred_at: new Date(occurredAt).toISOString(),
    };
    if (isMeasurement) {
      payload.reading = { reading_type: readingType, value: readingValue, unit: readingUnit };
    } else {
      payload.note = note;
    }

    saving = true;
    let postPersisted = false;
    submit.disabled = true;
    message.textContent = 'Saving owner update…';
    message.dataset.state = 'pending';
    try {
      const saved = await api.createOwnerUpdate(animalId, payload);
      postPersisted = true;
      savedOwnerUpdateId = saved.owner_update_id;
      message.textContent = 'Saved. Refreshing care updates…';
      message.dataset.state = 'success';
      await refreshSavedUpdate(saved.owner_update_id);
    } catch (error) {
      if (postPersisted || error.mayHavePersisted) {
        savedButRefreshFailed = true;
        submit.disabled = true;
        refresh.hidden = false;
        message.textContent = error.message || 'Update was saved, but Care updates could not refresh.';
      } else {
        message.textContent = error.message || 'Unable to save this update.';
      }
      message.dataset.state = 'error';
      saving = false;
      if (!savedButRefreshFailed) submit.disabled = false;
    }
  });

  refresh.addEventListener('click', async () => {
    if (!savedButRefreshFailed || saving) return;
    saving = true;
    refresh.disabled = true;
    message.textContent = 'Refreshing care updates…';
    message.dataset.state = 'pending';
    try {
      await refreshSavedUpdate(savedOwnerUpdateId);
    } catch (error) {
      message.textContent = error.message || 'Care updates could not refresh.';
      message.dataset.state = 'error';
      refresh.disabled = false;
      saving = false;
    }
  });

  const voicePanel = createVoiceUpdatePanel(animalId, onOwnerUpdatesRefresh);
  section.appendChild(voicePanel.element);
  voiceTrigger.addEventListener('click', () => {
    setFormOpen(false, { reset: true });
    voicePanel.open();
  });

  return section;
}

function renderOwnerUpdate(update) {
  const summary = formatOwnerUpdateSummary(update);
  return `
    <article class="owner-update-item">
      <div>
        <strong>${escapeHtml(summary.label)}</strong>
        <p>${escapeHtml(summary.detail)}</p>
      </div>
      <time datetime="${escapeHtml(update.occurred_at || '')}">Owner reported ${escapeHtml(formatOwnerReportedTimestamp(update.occurred_at))}</time>
    </article>
  `;
}

function localDateTimeValue(date = new Date()) {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

function createMonitoringLifecycleControls(animalId, profile, onRefresh) {
  const section = document.createElement('section');
  section.className = 'monitoring-lifecycle-controls';
  const lifecycle = monitoringLifecycleState(profile);
  const actions = lifecycleActions(profile);
  const cameraIndex = profile && profile.source_type === 'webcam' ? profile.source_reference : 0;
  const initialSourceMode = profile && profile.source_type === 'video' ? 'video' : 'camera';
  section.innerHTML = `
    <div class="monitoring-lifecycle-copy">
      <h2>${monitoringStatusText(profile)}</h2>
      <p>${lifecycle === 'source_not_connected'
        ? 'Connect a monitoring source before Comfort-z can collect visual observations.'
        : `${escapeHtml(sourceSamplingDetail(profile))}. ${lifecycle === 'active' ? 'Bounded observation windows are enabled.' : 'Start monitoring when you are ready to collect observations.'}`}</p>
    </div>
    <div class="monitoring-lifecycle-actions">
      ${actions.includes('connect') ? '<button type="button" class="btn btn-primary" data-connect>Connect source</button>' : ''}
      ${actions.includes('start') ? '<button type="button" class="btn btn-primary" data-start>Start monitoring</button>' : ''}
      ${actions.includes('pause') ? '<button type="button" class="btn btn-secondary" data-pause>Pause monitoring</button>' : ''}
      ${actions.includes('change') ? '<button type="button" class="btn btn-secondary" data-change>Change source</button>' : ''}
      ${actions.includes('disconnect') ? '<button type="button" class="btn btn-secondary" data-disconnect>Disconnect</button>' : ''}
      ${profile && profile.source_type === 'webcam' ? '<button type="button" class="btn btn-secondary" data-preview>Preview camera</button>' : ''}
      <button type="button" class="btn btn-secondary" data-edit-location>Edit location</button>
      <label class="profile-photo-action btn btn-secondary">
        Change profile photo
        <input type="file" data-profile-photo accept="image/jpeg,image/png,image/webp">
      </label>
    </div>
    <p class="monitoring-lifecycle-message" role="status" aria-live="polite"></p>
    <form class="profile-location-form" hidden novalidate>
      <div class="profile-location-copy">
        <strong>Location and outdoor context</strong>
        <p>Save an owner-provided location label. Outdoor weather context requires both coordinates; Comfort-z never infers them from your device or camera.</p>
      </div>
      <label>Location label <input name="location_name" type="text" maxlength="160" value="${escapeHtml((profile && profile.location_name) || '')}" placeholder="For example, Kuching, Sarawak"></label>
      <div class="profile-location-coordinates">
        <label>Latitude <input name="latitude" type="number" min="-90" max="90" step="any" value="${profile && profile.latitude != null ? escapeHtml(profile.latitude) : ''}" placeholder="1.5533"></label>
        <label>Longitude <input name="longitude" type="number" min="-180" max="180" step="any" value="${profile && profile.longitude != null ? escapeHtml(profile.longitude) : ''}" placeholder="110.3592"></label>
        <div class="profile-location-detect">
          <button type="button" class="btn btn-secondary" data-use-location>Use my location</button>
          <span>Requested only when you choose this button.</span>
        </div>
      </div>
      <div class="profile-location-actions">
        <button type="button" class="btn btn-secondary" data-cancel-location>Cancel</button>
        <button type="submit" class="btn btn-primary">Save location</button>
      </div>
    </form>
    <form class="connect-camera-form" hidden novalidate>
      <div>
        <strong>Connect monitoring source</strong>
        <p>Choose a live camera on this computer or upload one video for bounded monitoring. Uploading does not start monitoring.</p>
      </div>
      <div class="source-mode-picker" role="group" aria-label="Monitoring source type">
        <button type="button" class="source-mode-option" data-source-mode="camera" aria-pressed="false">Live camera</button>
        <button type="button" class="source-mode-option" data-source-mode="video" aria-pressed="false">Video file</button>
      </div>
      <label class="camera-source-fields">Camera index <input name="camera_index" type="number" min="0" step="1" required value="${escapeHtml(cameraIndex)}"></label>
      <label class="video-source-fields" hidden>
        <span>Choose video</span>
        <input name="monitoring_video" type="file" accept="video/mp4,video/webm,video/quicktime">
        <small class="video-source-filename">No video selected.</small>
      </label>
      <div class="connect-camera-actions">
        <button type="button" class="btn btn-secondary" data-preview>Preview camera</button>
        <button type="button" class="btn btn-secondary" data-cancel-connect>Cancel</button>
        <button type="submit" class="btn btn-primary">Connect camera</button>
      </div>
    </form>
    <div class="camera-preview" hidden></div>
  `;
  const form = section.querySelector('.connect-camera-form');
  const locationForm = section.querySelector('.profile-location-form');
  const message = section.querySelector('.monitoring-lifecycle-message');
  const preview = section.querySelector('.camera-preview');
  const cameraFields = section.querySelector('.camera-source-fields');
  const videoFields = section.querySelector('.video-source-fields');
  const videoInput = form.elements.monitoring_video;
  const videoFilename = section.querySelector('.video-source-filename');
  const sourceOptions = section.querySelectorAll('[data-source-mode]');
  const sourcePreviewButtons = section.querySelectorAll('[data-preview]');
  const sourceSubmit = form.querySelector('[type="submit"]');
  const locationSubmit = locationForm.querySelector('[type="submit"]');
  const useLocationButton = locationForm.querySelector('[data-use-location]');
  let sourceMode = initialSourceMode;
  const setSourceMode = (mode) => {
    sourceMode = mode;
    const usingCamera = mode === 'camera';
    cameraFields.hidden = !usingCamera;
    videoFields.hidden = usingCamera;
    form.elements.camera_index.required = usingCamera;
    videoInput.required = !usingCamera;
    sourcePreviewButtons.forEach((button) => { button.hidden = !usingCamera; });
    sourceOptions.forEach((option) => {
      const selected = option.dataset.sourceMode === mode;
      option.classList.toggle('is-selected', selected);
      option.setAttribute('aria-pressed', String(selected));
    });
    sourceSubmit.textContent = usingCamera ? 'Connect camera' : 'Upload video';
    message.textContent = '';
  };
  let previewState;
  const renderPreview = (snapshot) => {
    const hasImage = Boolean(snapshot.url);
    const isLoading = snapshot.status === 'loading';
    preview.hidden = !hasImage && snapshot.status !== 'loading';
    preview.dataset.status = snapshot.status;
    preview.setAttribute('aria-busy', String(isLoading));
    sourcePreviewButtons.forEach((button) => {
      button.disabled = isLoading;
      button.textContent = hasImage ? 'Refresh preview' : 'Preview camera';
    });
    preview.replaceChildren();
    if (preview.hidden) return;

    const heading = document.createElement('div');
    heading.className = 'camera-preview-heading';
    heading.innerHTML = '<strong>Camera preview</strong><span>Snapshot only — monitoring samples the camera during observation windows.</span>';
    preview.appendChild(heading);

    if (!hasImage) return;
    const media = document.createElement('div');
    media.className = 'camera-preview-media';
    const image = document.createElement('img');
    image.alt = 'Recent local camera snapshot';
    if (snapshot.pendingUrl === snapshot.url) {
      image.addEventListener('load', () => {
        previewState.imageLoaded(snapshot.url);
      }, { once: true });
      image.addEventListener('error', () => previewState.imageFailed(snapshot.url), { once: true });
    }
    image.src = snapshot.url;
    media.appendChild(image);
    if (isLoading) {
      const loading = document.createElement('div');
      loading.className = 'camera-preview-loading';
      loading.setAttribute('role', 'status');
      loading.textContent = 'Loading preview…';
      media.appendChild(loading);
    }
    preview.appendChild(media);
  };
  previewState = createCameraPreviewState({ animalId, render: renderPreview });
  previewState.render();
  const previewController = createCameraPreviewController({
    requestPreview: (index) => api.previewLocalCamera(index),
    previewState,
    setMessage: (text) => { message.textContent = text; },
  });
  const showPreview = () => {
    const index = Number(form.elements.camera_index.value);
    if (!Number.isInteger(index) || index < 0) {
      message.textContent = 'Enter a whole camera index of 0 or higher.';
      return;
    }
    return previewController.capture(index);
  };
  const openConnect = () => {
    locationForm.hidden = true;
    form.hidden = false;
    setSourceMode(sourceMode);
    (sourceMode === 'camera' ? form.elements.camera_index : videoInput).focus();
  };
  section.querySelector('[data-connect]')?.addEventListener('click', openConnect);
  section.querySelector('[data-change]')?.addEventListener('click', openConnect);
  section.querySelector('[data-cancel-connect]')?.addEventListener('click', () => { form.hidden = true; message.textContent = ''; });
  section.querySelector('[data-edit-location]').addEventListener('click', () => {
    form.hidden = true;
    locationForm.hidden = false;
    locationForm.elements.location_name.focus();
  });
  section.querySelector('[data-cancel-location]').addEventListener('click', () => {
    locationForm.hidden = true;
    message.textContent = '';
  });
  useLocationButton.addEventListener('click', async () => {
    message.textContent = 'Requesting your location…';
    try {
      await runAsyncControl(useLocationButton, async () => {
        const coordinates = await requestBrowserLocation();
        populateCoordinateFields(locationForm, coordinates);
        message.textContent = 'Coordinates added. Review them, add a location label if useful, then save.';
      });
    } catch (error) {
      message.textContent = error.message;
    }
  });
  sourceOptions.forEach((option) => option.addEventListener('click', () => setSourceMode(option.dataset.sourceMode)));
  sourcePreviewButtons.forEach((button) => button.addEventListener('click', showPreview));
  videoInput.addEventListener('change', () => {
    const selected = videoInput.files && videoInput.files[0];
    videoFilename.textContent = selected ? selected.name : 'No video selected.';
  });
  section.querySelector('[data-profile-photo]').addEventListener('change', async (event) => {
    const input = event.currentTarget;
    const photo = input.files && input.files[0];
    if (!photo) return;
    message.textContent = 'Saving profile photo…';
    try {
      await runAsyncControl(input, async () => {
        await api.uploadProfilePhoto(animalId, photo);
        message.textContent = '';
        await onRefresh();
      });
    } catch (error) {
      message.textContent = error.message || 'Unable to save the profile photo.';
    } finally {
      if (input.isConnected) input.value = '';
    }
  });
  section.querySelector('[data-start]')?.addEventListener('click', async (event) => {
    const button = event.currentTarget;
    try { await runAsyncControl(button, async () => { await api.startMonitoring(animalId); await onRefresh(); }); } catch (error) { message.textContent = error.message || 'Unable to start monitoring.'; form.hidden = false; }
  });
  section.querySelector('[data-pause]')?.addEventListener('click', async (event) => {
    const button = event.currentTarget;
    try { await runAsyncControl(button, async () => { await api.pauseMonitoring(animalId); await onRefresh(); }); } catch (error) { message.textContent = error.message || 'Unable to pause monitoring.'; form.hidden = false; }
  });
  section.querySelector('[data-disconnect]')?.addEventListener('click', async (event) => {
    const button = event.currentTarget;
    try { await runAsyncControl(button, async () => { await api.disconnectMonitoringSource(animalId); await onRefresh(); }); } catch (error) { message.textContent = error.message || 'Unable to disconnect the source.'; form.hidden = false; }
  });
  locationForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const locationName = locationForm.elements.location_name.value.trim();
    const latitudeValue = locationForm.elements.latitude.value.trim();
    const longitudeValue = locationForm.elements.longitude.value.trim();
    if (Boolean(latitudeValue) !== Boolean(longitudeValue)) {
      message.textContent = 'Enter both latitude and longitude, or leave both blank.';
      return;
    }
    const latitude = latitudeValue ? Number(latitudeValue) : null;
    const longitude = longitudeValue ? Number(longitudeValue) : null;
    if ((latitude !== null && (!Number.isFinite(latitude) || latitude < -90 || latitude > 90))
      || (longitude !== null && (!Number.isFinite(longitude) || longitude < -180 || longitude > 180))) {
      message.textContent = 'Enter valid latitude and longitude coordinates.';
      return;
    }
    message.textContent = 'Saving location…';
    try {
      await runAsyncControl(locationSubmit, async () => {
        await api.updateMonitoringLocation(animalId, {
          location_name: locationName || null,
          latitude,
          longitude,
        });
        message.textContent = '';
        await onRefresh();
      });
    } catch (error) {
      message.textContent = error.message || 'Unable to save this location.';
    }
  });
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    try {
      await runAsyncControl(sourceSubmit, async () => {
        if (sourceMode === 'video') {
          const video = videoInput.files && videoInput.files[0];
          if (!video) { message.textContent = 'Choose a video file first.'; return; }
          message.textContent = 'Uploading video…';
          await api.uploadMonitoringVideo(animalId, video);
        } else {
          const index = Number(form.elements.camera_index.value);
          if (!Number.isInteger(index) || index < 0) { message.textContent = 'Enter a whole camera index of 0 or higher.'; return; }
          message.textContent = 'Connecting camera…';
          await api.setMonitoringSource(animalId, { source_type: 'webcam', source_reference: index });
        }
        await onRefresh();
      });
    } catch (error) {
      message.textContent = error.message || (sourceMode === 'video' ? 'Unable to upload this video.' : 'Unable to connect this camera.');
    }
  });
  setSourceMode(sourceMode);
  return section;
}

/**
 * 0. Editorial Animal Profile Hero
 */
function createAnimalHero(animalId, profile, latestObs) {
  const hero = document.createElement('section');
  hero.className = 'animal-identity-hero';
  hero.setAttribute('aria-label', 'Animal Identity Profile');

  const name = (profile && profile.animal_name) || (latestObs && latestObs.animal_name) || animalId;
  const species = profile ? profileSpeciesLabel(profile) : ((latestObs && latestObs.expected_species) || 'Species not recorded');
  const goal = (profile && profile.monitoring_goal) || 'Continuous welfare monitoring for ' + name;
  const active = profile ? profile.active === true : false;
  const mode = profile ? profile.current_sampling_mode || 'normal' : 'normal';
  const used = profile ? profile.samples_used_in_current_period || 0 : (latestObs ? 1 : 0);
  const budget = profile ? profile.daily_sample_budget || 24 : 24;
  const remaining = Math.max(0, budget - used);
  const hasSource = hasMonitoringSource(profile);

  // Format source type clearly
  const sourceLabel = sourceDisplayLabel(profile);

  // Future profile image support: if provided, render image; else render decorative silhouette
  const hasUploadedPhoto = Boolean(profile && profile.profileImage);
  const legacyPhotoHtml = hasUploadedPhoto
    ? `<img src="${escapeHtml(profile.profileImage)}" alt="Portrait of ${escapeHtml(name)}" class="hero-uploaded-portrait">`
    : `
      <!-- Stylized Betta Silhouette (Decorative UI representation, not monitoring evidence) -->
      <svg class="hero-decorative-silhouette" viewBox="0 0 200 160" fill="currentColor" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
        <path d="M170,80 C155,45 125,20 85,25 C60,28 35,45 15,40 C28,58 45,65 55,75 C45,85 20,95 10,120 C35,110 60,125 90,130 C130,135 160,115 170,80 Z" opacity="0.25"/>
        <path d="M85,35 C115,30 145,50 155,80 C145,105 120,120 90,118 C65,115 50,100 55,78 C50,65 65,40 85,35 Z" opacity="0.6"/>
        <path d="M150,75 C165,65 185,55 195,45 C190,65 180,85 190,105 C180,95 165,85 150,75 Z" opacity="0.4"/>
        <circle cx="75" cy="62" r="3" fill="#FAF8F5"/>
      </svg>
      <span class="hero-silhouette-caption">Decorative silhouette representation • Animal profile photograph not configured</span>
    `;

  const hasProfilePhoto = Boolean(profileImageSource(profile || {}));
  const photoHtml = renderAnimalVisual(
    profile || { expected_species: species },
    { className: 'hero-profile-visual', alt: `Profile of ${name}` }
  );

  hero.innerHTML = `
    <div class="hero-identity-main">
      <div class="hero-status-row">
        <span class="badge ${hasSource && active ? 'badge-normal' : 'badge-neutral'}">
          <span class="badge-dot"></span>
          ${!hasSource ? 'Monitoring source not connected' : active ? 'Monitoring active' : 'Monitoring paused'}
        </span>
        <span style="font-size: var(--font-size-label); color: var(--color-text-muted);">
          ID: ${escapeHtml(animalId)}
        </span>
      </div>

      <h1 class="hero-animal-name">${escapeHtml(name)}</h1>
      <div class="hero-species-title">${escapeHtml(species)}</div>

      <p class="hero-goal-lead">
        <strong>Monitoring Goal:</strong> ${escapeHtml(goal)}
      </p>

      <div class="hero-telemetry-strip">
        <div class="hero-telemetry-item">
          Enclosure: <strong>${escapeHtml((profile && profile.enclosure_type) || 'Not recorded')}</strong>
        </div>
        <div class="hero-telemetry-item">
          Visual Feed: <strong>${escapeHtml(sourceLabel)}</strong>
        </div>
        <div class="hero-telemetry-item">
          Sampling Mode: <strong style="text-transform: capitalize;">${escapeHtml(mode)} (300s)</strong>
        </div>
        <div class="hero-telemetry-item">
          Daily Quota: <strong>${remaining} of ${budget} left</strong>
        </div>
      </div>
    </div>

    <div class="hero-portrait-frame${hasProfilePhoto ? ' has-profile-photo' : ''}">
      ${photoHtml}
      ${hasProfilePhoto ? '' : '<span class="hero-silhouette-caption">Decorative profile fallback</span>'}
    </div>
  `;

  return hero;
}

/**
 * 1. Unified Observation Stage (Commanding Hero Canvas - Preserved)
 */
function createObservationStage(animalId, profile, latestObs, onRefresh) {
  const stage = document.createElement('section');
  stage.className = 'observation-stage';
  stage.setAttribute('aria-label', 'Visual Monitoring and Observation Stage');

  const hasSource = hasMonitoringSource(profile);
  const monitoringActive = profile && profile.active === true;
  
  const sourceBadge = sourceDisplayLabel(profile);

  const gemini = latestObs ? (latestObs.gemini_observation || {}) : {};
  const isVisible = gemini.animal_visible !== false;
  const severity = latestObs ? (latestObs.severity || gemini.severity || 'monitor') : 'monitor';
  const confidence = gemini.confidence != null ? formatConfidence(gemini.confidence) : 'Not available';

  // Top Bar of Stage
  const topBar = document.createElement('div');
  topBar.className = 'stage-top-bar';
  topBar.innerHTML = `
    <div style="display: flex; align-items: center; gap: var(--space-3);">
      <span style="font-weight: 700; color: #FFFFFF; letter-spacing: 0.05em; text-transform: uppercase;">Visual Feed</span>
      <span>•</span>
      <span style="color: var(--color-stage-text-muted);">${escapeHtml(sourceBadge)}</span>
    </div>
    <div>
      <span>${latestObs ? 'Sampled: ' + formatTimestamp(latestObs.timestamp) : hasSource ? 'Awaiting observation cycle' : 'Source required before monitoring'}</span>
    </div>
  `;
  stage.appendChild(topBar);

  // Main Viewport Split
  const viewportSplit = document.createElement('div');
  viewportSplit.className = 'stage-viewport-split';

  // Left Pane: Media Frame
  const mediaPane = document.createElement('div');
  mediaPane.className = 'stage-media-pane';
  if (!hasSource) {
    mediaPane.innerHTML = `
      <div class="stage-video-frame">
        <div class="stage-placeholder">
          <h3>Monitoring source not connected</h3>
          <p style="font-size: var(--font-size-body); max-width: 340px; margin: 0 auto; line-height: 1.5;">
            This animal profile is saved. Connect a monitoring source before Comfort-z can collect observations.
          </p>
        </div>
      </div>
    `;
  } else {
    mediaPane.innerHTML = `
      <div class="stage-video-frame">
        <div class="stage-placeholder">
          <h3>${profile.source_type === 'webcam' ? 'Camera connected' : 'Video source connected'}</h3>
          <p style="font-size: var(--font-size-body); max-width: 340px; margin: 0 auto; line-height: 1.5;">
            ${profile.source_type === 'webcam'
              ? 'Comfort-z samples this camera on the computer that has access to it. Live playback is not shown here.'
              : 'Comfort-z samples this configured video source through OpenCV. Playback is not shown here.'}
          </p>
        </div>
        <div class="stage-source-badge">
          <span class="badge-dot" style="background-color: var(--color-peach);"></span>
          <span>${escapeHtml(sourceBadge)}</span>
        </div>
      </div>
    `;

  }
  viewportSplit.appendChild(mediaPane);

  // Right Pane: Live Behavioral Telemetry & Gemini Synthesis
  const telemetryPane = document.createElement('div');
  telemetryPane.className = 'stage-telemetry-pane';

  if (!latestObs) {
    telemetryPane.innerHTML = `
      <div class="stage-telemetry-header">
        <span class="stage-telemetry-title">Observation</span>
        <span class="badge ${hasSource ? 'badge-stage-monitor' : 'badge-neutral'}">${hasSource ? 'Awaiting observation' : 'Source not connected'}</span>
      </div>
      <p style="color: var(--color-stage-text-subtle); font-size: var(--font-size-body); line-height: 1.5;">
        ${hasSource ? (monitoringActive ? 'No visual observation records saved yet. Run one bounded observation when you are ready.' : 'Monitoring is paused. Start monitoring before collecting an observation.') : 'No observation can be collected until a monitoring source is connected.'}
      </p>
    `;
  } else {
    telemetryPane.innerHTML = `
      <div>
        <div class="stage-telemetry-header">
          <span class="stage-telemetry-title">Observation</span>
          <span class="badge badge-stage-${severity}">
            <span class="badge-dot"></span>
            ${isVisible ? 'Animal visible' : 'Animal not visible'}
          </span>
        </div>
        <div style="margin-top: var(--space-4);">
          <div class="stage-obs-headline">
            ${escapeHtml(gemini.behavioral_interpretation || latestObs.explanation || 'Visual observation recorded.')}
          </div>
          ${gemini.uncertainty ? `<div class="stage-obs-uncertainty"><em>Context:</em> ${escapeHtml(gemini.uncertainty)}</div>` : ''}
        </div>
      </div>

      <div class="stage-kv-table">
        <div class="stage-kv-row">
          <span class="stage-kv-key">Posture</span>
          <span class="stage-kv-val">${escapeHtml(gemini.posture || 'Not recorded')}</span>
        </div>
        <div class="stage-kv-row">
          <span class="stage-kv-key">Movement</span>
          <span class="stage-kv-val">${escapeHtml(gemini.apparent_movement || 'Not recorded')}</span>
        </div>
        <div class="stage-kv-row">
          <span class="stage-kv-key">Activity Level</span>
          <span class="stage-kv-val">${escapeHtml(gemini.activity_level || 'Not recorded')}</span>
        </div>
        <div class="stage-kv-row">
          <span class="stage-kv-key">Observation Confidence</span>
          <span class="stage-kv-val">${escapeHtml(confidence)}</span>
        </div>
      </div>

      ${gemini.environmental_observations && gemini.environmental_observations.length > 0 ? `
        <div class="stage-enclosure-visuals">
          <strong style="color: var(--color-stage-accent);">Enclosure Visuals:</strong> ${escapeHtml(gemini.environmental_observations.join(', '))}
        </div>
      ` : ''}
    `;
  }
  viewportSplit.appendChild(telemetryPane);
  stage.appendChild(viewportSplit);

  // Bottom Action Bar of Stage
  const bottomBar = document.createElement('div');
  bottomBar.className = 'stage-bottom-bar';
  bottomBar.innerHTML = hasSource && monitoringActive ? `
    <div style="display: flex; align-items: center; gap: var(--space-4); flex-wrap: wrap;">
      <button id="btn-run-observation" class="btn btn-stage-primary">
        Run observation now
      </button>
      <div id="stage-action-status" style="display: none;" role="status" aria-live="polite"></div>
    </div>
    <span style="font-size: var(--font-size-label); color: var(--color-stage-text-muted);">One bounded frame window</span>
  ` : `
    <span style="font-size: var(--font-size-label); color: var(--color-stage-text-muted);">
      ${hasSource ? 'Start monitoring before running an observation.' : 'Connect a source before monitoring is available.'}
    </span>
  `;
  stage.appendChild(bottomBar);

  // Wire Action Button with execution locks and safe lifecycle
  const runBtn = bottomBar.querySelector('#btn-run-observation');
  const statusEl = bottomBar.querySelector('#stage-action-status');

  if (runBtn) {
    let isExecuting = false;

    runBtn.addEventListener('click', async () => {
      if (isExecuting) return;
      isExecuting = true;

      runBtn.disabled = true;
      runBtn.classList.add('btn-disabled');
      runBtn.textContent = 'Observing frame...';

      if (statusEl) {
        statusEl.style.display = 'inline-flex';
        statusEl.className = 'stage-action-status running';
        statusEl.textContent = 'Executing bounded observation cycle...';
      }

      try {
        const response = await api.runNextWindow(animalId, 1);

        if (statusEl) {
          statusEl.className = 'stage-action-status success';
          const reason = response && response.ended_reason ? ` (${response.ended_reason})` : '';
          statusEl.textContent = `Observation complete${reason}. Updating console...`;
        }

        if (typeof onRefresh === 'function') {
          setTimeout(async () => {
            await onRefresh();
          }, 800);
        }
      } catch (err) {
        if (statusEl) {
          statusEl.className = 'stage-action-status error';
          statusEl.textContent = `Observation failed: ${err.message || 'Server error'}`;
        }
      } finally {
        isExecuting = false;
        runBtn.disabled = false;
        runBtn.classList.remove('btn-disabled');
        runBtn.textContent = 'Run observation now';
      }
    });
  }

  return stage;
}

/**
 * 2. Full-Width Dual-Context Environmental Reasoning Ribbon (No Boxy Cards)
 */
function createTelemetryRibbon(profile, latestObs, ownerUpdates, currentEnvironment) {
  const ribbon = document.createElement('section');
  ribbon.className = 'telemetry-ribbon';
  ribbon.setAttribute('aria-label', 'Environmental Telemetry Context');
  const formatTimestamp = formatOwnerReportedTimestamp;

  const enclosureReading = selectEnvironmentPanelReading({
    ownerUpdates,
    latestObservation: latestObs,
    profile,
  });
  const readings = (latestObs && latestObs.direct_environment_readings) ||
                   (profile && profile.direct_environment_readings) || [];

  const ambient = createAmbientWeatherView({
    profile,
    currentEnvironment,
    latestObservation: latestObs,
  });
  const ambientDetails = [
    ambient.condition,
    ambient.humidity ? `${ambient.humidity} humidity` : null,
  ].filter(Boolean).join(' • ');
  const ambientStatus = ambient.status === 'unavailable'
    ? 'Current outdoor weather could not be retrieved. Try again later.'
    : ambient.status === 'not_configured'
      ? 'Add a location and coordinates to show current outdoor weather.'
      : ambient.historical
        ? 'Last recorded outdoor context. Save coordinates to retrieve current conditions independently.'
        : 'Current conditions for the saved location.';
  const ambientProvenance = ambient.provider
    ? `${ambient.provider}${ambient.observedAt ? ` • Observed ${formatTimestamp(ambient.observedAt)}` : ''}`
    : 'No current weather source available';

  // Left Half: Ambient Outdoor Weather (Step 1 in Reasoning Chain)
  const halfOutdoor = document.createElement('div');
  halfOutdoor.className = 'telemetry-strip-half';
  halfOutdoor.innerHTML = `
    <div class="ribbon-header" style="color: var(--color-primary);">
      <span class="badge-dot" style="background-color: var(--color-primary);"></span>
      <span>1. Ambient / Outdoor Weather (${escapeHtml(ambient.locationName)})</span>
    </div>
    <div style="display: flex; align-items: baseline; gap: var(--space-3);">
      <span class="ribbon-value-lead${ambient.status === 'available' || ambient.status === 'historical' ? '' : ' is-unavailable'}">${escapeHtml(ambient.temperature)}</span>
      ${ambientDetails ? `<span class="ribbon-sub-metric" style="text-transform: capitalize;">${escapeHtml(ambientDetails)}</span>` : ''}
    </div>
    <div class="ribbon-reasoning-flow">
      <strong>Outdoor context:</strong> ${escapeHtml(ambientStatus)}
    </div>
    <p class="ribbon-provenance-caption">
      ${escapeHtml(ambientProvenance)} • NOT AN ENCLOSURE SENSOR READING
    </p>
  `;
  ribbon.appendChild(halfOutdoor);

  // Right Half: Owner-provided enclosure readings (Step 2 in Reasoning Chain)
  const halfEnclosure = document.createElement('div');
  halfEnclosure.className = 'telemetry-strip-half';

  let enclosureValueHtml = '';
  if (enclosureReading?.source === 'owner_update') {
    enclosureValueHtml = `
      <div style="display: flex; align-items: baseline; gap: var(--space-3);">
        <span class="ribbon-value-lead">${escapeHtml(formatDirectReadingValue(enclosureReading.reading))}</span>
        <span class="ribbon-sub-metric">${escapeHtml(formatReadingType(enclosureReading.reading.reading_type))}</span>
      </div>
      <p class="ribbon-provenance-caption" style="margin: var(--space-2) 0 0;">
        Owner reported ${escapeHtml(formatTimestamp(enclosureReading.ownerUpdate.occurred_at))}${enclosureReading.isFresh ? '' : ' • May be outdated'}
      </p>
    `;
  } else if (enclosureReading) {
    enclosureValueHtml = `
      <div style="display: flex; align-items: baseline; gap: var(--space-3);">
        <span class="ribbon-value-lead">${escapeHtml(formatDirectReadingValue(enclosureReading.reading))}</span>
        <span class="ribbon-sub-metric">${escapeHtml(formatReadingType(enclosureReading.reading.reading_type))}</span>
      </div>
    `;
  } else if (readings.length > 0) {
    enclosureValueHtml = `
      <div style="display: flex; align-items: baseline; gap: var(--space-3);">
        <span class="ribbon-value-lead">${readings[0].value}°${escapeHtml(readings[0].unit || 'C')}</span>
        <span class="ribbon-sub-metric" style="text-transform: capitalize;">${escapeHtml(readings[0].reading_type || 'Water Temperature')}</span>
      </div>
    `;
  } else {
    enclosureValueHtml = `
      <div style="display: flex; align-items: baseline; gap: var(--space-3);">
        <span class="ribbon-value-lead" style="font-size: var(--font-size-headline); color: var(--color-text-muted); font-weight: 600;">Not recorded</span>
        <span class="ribbon-sub-metric">No direct enclosure reading recorded</span>
      </div>
    `;
  }

  const storedMissingReq = (latestObs && latestObs.missing_direct_reading_requests && latestObs.missing_direct_reading_requests[0]) || '';
  const missingReq = shouldSuppressMissingReadingRequest(storedMissingReq, enclosureReading)
    ? ''
    : storedMissingReq;

  halfEnclosure.innerHTML = `
    <div class="ribbon-header" style="color: var(--color-secondary);">
      <span class="badge-dot" style="background-color: var(--color-secondary);"></span>
      <span>2. Owner-Reported Enclosure Reading (${escapeHtml((profile && profile.enclosure_type) || 'Type not recorded')})</span>
    </div>
    ${enclosureValueHtml}
    <div class="ribbon-reasoning-flow">
      ${enclosureReading?.source === 'owner_update'
        ? `<strong>Owner context:</strong> Manually reported enclosure measurement. Last updated ${escapeHtml(formatOwnerMeasurementAge(enclosureReading.ownerUpdate))}.${missingReq ? ` ${escapeHtml(missingReq)}` : ''}`
        : missingReq
          ? `<strong>Sensor Advisory:</strong> ${escapeHtml(missingReq)}`
          : enclosureReading
            ? `<strong>Owner context:</strong> Manually reported enclosure measurement.`
          : `<strong>Enclosure Assessment:</strong> No owner-provided enclosure reading is available.`}
    </div>
  `;
  ribbon.appendChild(halfEnclosure);

  return ribbon;
}

/**
 * 3. Longitudinal Trend & Policy Decision (Open Section)
 */
function createTrendModule(latestObs) {
  const module = document.createElement('section');
  module.className = 'editorial-open-section';

  const header = document.createElement('div');
  header.className = 'editorial-section-header';
  header.innerHTML = `
    <h3 class="editorial-section-title">Longitudinal Trend & Action Policy</h3>
    <span class="editorial-section-meta">7-Day Baseline</span>
  `;
  module.appendChild(header);

  if (!latestObs) {
    const empty = document.createElement('div');
    empty.className = 'empty-inline';
    empty.textContent = 'Trend analysis requires at least one evaluated observation record.';
    module.appendChild(empty);
    return module;
  }

  const trendRaw = latestObs.trend || 'insufficient_visibility';
  const trendInfo = getTrendLabel(trendRaw);
  const decision = latestObs.decision || {};
  const alertStatus = latestObs.alert_status || decision.alert_status || false;
  const reason = decision.reason || latestObs.explanation || 'Observation evaluated against historical baseline.';
  const action = decision.recommended_action || 'Continue routine monitoring.';

  const headlineRow = document.createElement('div');
  headlineRow.className = 'trend-headline-row';
  headlineRow.innerHTML = `
    <div class="trend-pattern-title">Pattern: ${escapeHtml(trendInfo)}</div>
    <span class="badge ${alertStatus ? 'badge-concerning' : 'badge-normal'}">
      <span class="badge-dot"></span>
      ${alertStatus ? 'Alert Active' : 'No Alert'}
    </span>
  `;
  module.appendChild(headlineRow);

  const narrative = document.createElement('p');
  narrative.className = 'trend-narrative-text';
  narrative.textContent = reason;
  module.appendChild(narrative);

  const guidanceBox = document.createElement('div');
  guidanceBox.className = 'trend-guidance-box';
  guidanceBox.innerHTML = `
    <div class="trend-guidance-label">Recommended Care Action</div>
    <div class="trend-guidance-text">${escapeHtml(action)}</div>
  `;
  module.appendChild(guidanceBox);

  return module;
}

/**
 * 4. Grounded Research Dispatch (Open Section)
 */
function createResearchModule(latestObs) {
  const module = document.createElement('section');
  module.className = 'editorial-open-section';

  const header = document.createElement('div');
  header.className = 'editorial-section-header';
  header.innerHTML = `
    <h3 class="editorial-section-title">Grounded Research Findings</h3>
    <span class="editorial-section-meta">Conditional Google Search</span>
  `;
  module.appendChild(header);

  if (!latestObs || !latestObs.research_context) {
    const empty = document.createElement('div');
    empty.className = 'empty-inline';
    empty.textContent = 'No research inquiry triggered for current observation.';
    module.appendChild(empty);
    return module;
  }

  const rc = latestObs.research_context;
  const decision = rc.decision || {};
  const result = rc.result;

  if (result) {
    const topic = document.createElement('div');
    topic.className = 'research-topic';
    topic.textContent = result.query || decision.research_question || 'Grounded care context';
    module.appendChild(topic);

    const summary = document.createElement('div');
    summary.className = 'research-summary';
    summary.textContent = result.evidence_summary || 'Citation-backed research context was saved with this observation.';
    module.appendChild(summary);

    if (result.community_summary) {
      const community = document.createElement('p');
      community.className = 'research-community-note';
      community.textContent = result.community_summary;
      module.appendChild(community);
    }
    if (result.conflicts_or_uncertainty) {
      const caution = document.createElement('p');
      caution.className = 'research-caution-note';
      caution.textContent = result.conflicts_or_uncertainty;
      module.appendChild(caution);
    }
    if (result.sources && result.sources.length > 0) {
      const citationList = document.createElement('div');
      citationList.className = 'research-citation-list';
      result.sources.forEach((source) => {
        const cItem = document.createElement('div');
        cItem.className = 'citation-item';
        const category = (source.category || 'unknown').toLowerCase();
        cItem.innerHTML = `
          <div class="citation-top-row">
            <a href="${escapeHtml(source.reference || '#')}" target="_blank" rel="noopener noreferrer" class="citation-link">${escapeHtml(source.title || 'Cited source')}</a>
            <span class="citation-category-pill ${escapeHtml(category)}">${escapeHtml(category.replace(/_/g, ' '))}</span>
          </div>
          ${source.source_name ? `<span class="citation-source-name">${escapeHtml(source.source_name)}</span>` : ''}
          <div class="citation-evidence">${escapeHtml(source.evidence || '')}</div>
        `;
        citationList.appendChild(cItem);
      });
      module.appendChild(citationList);
    }
    return module;
  }

  if (rc.failure) {
    const failure = document.createElement('div');
    failure.className = 'empty-inline';
    failure.textContent = rc.failure;
    module.appendChild(failure);
    return module;
  }

  if (!decision.needed) {
    const notNeeded = document.createElement('p');
    notNeeded.style.fontSize = 'var(--font-size-body)';
    notNeeded.style.color = 'var(--color-text-secondary)';
    notNeeded.style.lineHeight = '1.5';
    notNeeded.innerHTML = `<strong>Inquiry Status:</strong> Not triggered. ${escapeHtml(decision.reason || 'Animal behavior matches baseline or visibility is insufficient for research.')}`;
    module.appendChild(notNeeded);
    return module;
  }

  const pending = document.createElement('div');
  pending.className = 'empty-inline';
  pending.textContent = 'Research was triggered but no grounded findings were saved.';
  module.appendChild(pending);

  return module;
}

/**
 * 5. Daily Care Summaries Module (Open Section)
 */
function createReportsModule(animalId, profile, reports, onRefresh) {
  const module = document.createElement('section');
  module.className = 'editorial-open-section';
  const hasSource = hasMonitoringSource(profile);

  const header = document.createElement('div');
  header.className = 'editorial-section-header';
  header.innerHTML = `
    <h3 class="editorial-section-title">Daily Care Summaries</h3>
    <span class="editorial-section-meta">${reports.length} Synthesized</span>
  `;
  module.appendChild(header);

  if (hasSource) {
    const actionStrip = document.createElement('div');
    actionStrip.style.display = 'flex';
    actionStrip.style.justifyContent = 'space-between';
    actionStrip.style.alignItems = 'center';
    actionStrip.style.flexWrap = 'wrap';
    actionStrip.style.gap = 'var(--space-3)';
    actionStrip.style.marginBottom = 'var(--space-2)';
    actionStrip.innerHTML = `
      <button id="btn-generate-report" class="btn btn-secondary">
        Generate daily report
      </button>
      <span style="font-size: var(--font-size-label); color: var(--color-text-muted);">
        Synthesizes 24h structured history
      </span>
    `;
    module.appendChild(actionStrip);
  } else {
    const sourceNotice = document.createElement('p');
    sourceNotice.className = 'empty-inline';
    sourceNotice.textContent = 'Daily reports are unavailable until a monitoring source is connected.';
    module.appendChild(sourceNotice);
  }

  const statusEl = document.createElement('div');
  statusEl.id = 'report-action-status';
  statusEl.style.display = 'none';
  statusEl.setAttribute('role', 'status');
  statusEl.setAttribute('aria-live', 'polite');
  module.appendChild(statusEl);

  if (reports.length === 0) {
    const empty = document.createElement('div');
    empty.className = 'empty-inline';
    empty.textContent = 'No daily reports generated yet. Reports are synthesized from persisted structured history.';
    module.appendChild(empty);
  } else {
    reports.forEach(r => {
      const card = document.createElement('div');
      card.className = 'report-card';
      const narrative = r.narrative || {};
      const ownerContext = Array.isArray(narrative.owner_reported_context)
        ? narrative.owner_reported_context
        : [];
      card.innerHTML = `
        <div class="report-card-header">
          <span>24h Report • ${formatTimestamp(r.generated_at)}</span>
          <span class="badge badge-neutral" style="font-size: var(--font-size-label);">${r.valid_observation_count || 0} valid frames</span>
        </div>
        <div class="report-narrative-text">
          <strong>Activity & Behavior:</strong> ${escapeHtml(narrative.overall_activity_behavior || 'Summary available in record.')}
        </div>
        <div style="font-size: var(--font-size-label); color: var(--color-text-muted);">
          Concerning: ${(r.concerning_observation_ids || []).length} • Alerts: ${(r.alert_observation_ids || []).length}
        </div>
        ${ownerContext.length > 0 ? `
          <div style="margin-top: 9px; color: var(--color-text-secondary); font-size: .72rem; line-height: 1.45;">
            <strong>Owner-provided context:</strong> ${escapeHtml(ownerContext.join(' '))}
          </div>
        ` : ''}
      `;
      module.appendChild(card);
    });
  }

  // Wire Button
  const generateBtn = module.querySelector('#btn-generate-report');
  if (generateBtn) {
    let isGenerating = false;

    generateBtn.addEventListener('click', async () => {
      if (isGenerating) return;
      isGenerating = true;

      generateBtn.disabled = true;
      generateBtn.classList.add('btn-disabled');
      generateBtn.textContent = 'Synthesizing...';

      statusEl.style.display = 'flex';
      statusEl.className = 'action-status status-running';
      statusEl.textContent = 'Synthesizing daily monitoring report from structured history...';

      try {
        const response = await api.generateDailyReport(animalId);

        statusEl.className = 'action-status status-success';
        const reportId = response && response.report_id ? `Report ${response.report_id.substring(0, 8)}` : 'Daily report';
        statusEl.textContent = `${reportId} generated successfully. Updating console...`;

        if (typeof onRefresh === 'function') {
          setTimeout(async () => {
            await onRefresh();
          }, 800);
        }
      } catch (err) {
        statusEl.className = 'action-status status-error';
        statusEl.textContent = `Report generation failed: ${err.message || 'Server error'}`;
      } finally {
        isGenerating = false;
        generateBtn.disabled = false;
        generateBtn.classList.remove('btn-disabled');
        generateBtn.textContent = 'Generate daily report';
      }
    });
  }

  return module;
}

/**
 * 6. Minimalist Chronological Observation Log (Audit Ledger)
 */
function createTimelineModule(observations) {
  const module = document.createElement('section');
  module.className = 'editorial-open-section';

  const header = document.createElement('div');
  header.className = 'editorial-section-header';
  header.innerHTML = `
    <h3 class="editorial-section-title">Observation Log</h3>
    <span class="editorial-section-meta">${observations.length} Recorded</span>
  `;
  module.appendChild(header);

  if (!observations.length) {
    const empty = document.createElement('div');
    empty.className = 'empty-inline';
    empty.textContent = 'No observation history recorded yet.';
    module.appendChild(empty);
    return module;
  }

  const list = document.createElement('div');
  list.className = 'timeline-chronological-list';

  observations.slice(0, 8).forEach(obs => {
    const row = document.createElement('div');
    row.className = 'timeline-row';

    const severity = obs.severity || 'monitor';
    const gemini = obs.gemini_observation || {};
    const text = gemini.behavioral_interpretation || obs.explanation || 'Observation recorded.';

    row.innerHTML = `
      <div class="timeline-pip ${severity}"></div>
      <div class="timeline-timestamp">${formatTimestamp(obs.timestamp)}</div>
      <div class="timeline-text">${escapeHtml(text)}</div>
      <div style="font-size: var(--font-size-label); color: var(--color-text-muted); margin-top: 2px;">
        ${escapeHtml(obs.source_info || '')}
      </div>
    `;
    list.appendChild(row);
  });

  module.appendChild(list);
  return module;
}

/**
 * 7. Compact Footer Diagnostics Ribbon
 */
function createDiagnosticsRibbon(profile, latestObs) {
  const ribbon = document.createElement('footer');
  ribbon.className = 'diagnostics-ribbon';

  const mode = profile ? profile.current_sampling_mode || 'normal' : 'normal';
  const used = profile ? profile.samples_used_in_current_period || 0 : (latestObs ? 1 : 0);
  const budget = profile ? profile.daily_sample_budget || 24 : 24;
  const remaining = Math.max(0, budget - used);
  const lastRun = profile && profile.last_monitoring_run ? formatTimestamp(profile.last_monitoring_run) : (latestObs ? formatTimestamp(latestObs.timestamp) : 'Not yet run');

  ribbon.innerHTML = `
    <span><strong>Operational Mode:</strong> ${escapeHtml(mode)} (300s window)</span>
    <span><strong>Quota Remaining:</strong> ${remaining} of ${budget} daily samples</span>
    <span><strong>Latest observation:</strong> ${escapeHtml(lastRun)}</span>
  `;

  return ribbon;
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
