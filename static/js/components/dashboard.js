/**
 * Animal Monitoring Dashboard Component
 * Renders the detailed monitoring view with authentic backend data.
 */

import { api } from '../api.js';
import {
  formatTimestamp,
  getSeverityBadge,
  getTrendLabel,
  formatConfidence,
} from '../state.js';

export function renderDashboard(animalId, profile, observations, reports, navigate, onRefresh) {
  const container = document.createElement('div');
  container.className = 'dashboard-container';

  const name = (profile && profile.animal_name) || (observations[0] && observations[0].animal_name) || animalId;
  const species = (profile && profile.expected_species) || (observations[0] && observations[0].expected_species) || 'Species not recorded';
  const goal = (profile && profile.monitoring_goal) || 'Keep an eye on ' + name;
  const latestObs = observations && observations.length > 0 ? observations[0] : null;

  // Breadcrumb
  const breadcrumb = document.createElement('div');
  breadcrumb.className = 'nav-breadcrumb';
  breadcrumb.innerHTML = `
    <a id="back-to-overview">← All Animals</a>
    <span>/</span>
    <span>${escapeHtml(name)}</span>
  `;
  breadcrumb.querySelector('#back-to-overview').addEventListener('click', () => navigate('#/overview'));
  container.appendChild(breadcrumb);

  // Page Header
  const header = document.createElement('div');
  header.className = 'page-header';
  const severityInfo = latestObs ? getSeverityBadge(latestObs.severity) : { class: 'badge-neutral', label: 'No Data' };
  header.innerHTML = `
    <div class="page-title">
      <h2>${escapeHtml(name)} <span class="species-tag">(${escapeHtml(species)})</span></h2>
      <div style="margin-top: 4px; font-size: 0.85rem; color: var(--color-text-secondary);">
        <strong>Monitoring Goal:</strong> ${escapeHtml(goal)}
      </div>
    </div>
    <div class="page-actions">
      <span class="badge ${profile && profile.active ? 'badge-normal' : 'badge-neutral'}">
        ${profile ? (profile.active ? 'Monitoring Active' : 'Profile Inactive') : 'Saved History Mode'}
      </span>
      <span class="badge ${severityInfo.class}">
        ${severityInfo.label}
      </span>
    </div>
  `;
  container.appendChild(header);

  // 2-Column Grid
  const grid = document.createElement('div');
  grid.className = 'dashboard-grid';

  // Left Column
  const colLeft = document.createElement('div');
  colLeft.className = 'col-left';

  // 1. Camera / Video Panel
  colLeft.appendChild(createVideoPanel(animalId, profile, latestObs, onRefresh));

  // 2. Environment Context Card (Direct Enclosure vs Outdoor Weather)
  colLeft.appendChild(createEnvironmentCard(profile, latestObs));

  // 3. Monitoring Budget & Mode
  colLeft.appendChild(createBudgetCard(profile, latestObs));

  // Right Column
  const colRight = document.createElement('div');
  colRight.className = 'col-right';

  // 1. Latest Observation & Behavioral Interpretation
  colRight.appendChild(createObservationCard(latestObs));

  // 2. Trend & Alert Policy Decision Card
  colRight.appendChild(createTrendDecisionCard(latestObs));

  // 3. Conditional Research Findings Card
  colRight.appendChild(createResearchCard(latestObs));

  // 4. Historical Observations Timeline
  colRight.appendChild(createTimelineCard(observations));

  // 5. Daily Reports Section
  colRight.appendChild(createReportsCard(animalId, reports, onRefresh));

  grid.appendChild(colLeft);
  grid.appendChild(colRight);
  container.appendChild(grid);

  return container;
}

/**
 * 1. Video & Source Area
 */
function createVideoPanel(animalId, profile, latestObs, onRefresh) {
  const card = document.createElement('div');
  card.className = 'card';

  const sourceInfo = (profile && profile.source_reference) || (latestObs && latestObs.source_info) || 'Source not specified';
  const isVideo = !profile || profile.source_type === 'video' || String(sourceInfo).includes('.mp4');

  card.innerHTML = `
    <div class="card-header">
      <span class="card-title">📹 Monitoring Visual Source</span>
      <span class="badge badge-neutral">${isVideo ? 'Prerecorded Video' : 'Webcam / Stream'}</span>
    </div>
    <div class="video-container">
      <video class="video-player" controls muted preload="metadata" playsinline>
        <source src="/demo-video/raku.mp4" type="video/mp4">
        Your browser does not support video playback.
      </video>
      <div class="video-overlay-badge" id="video-provenance-tag">
        ${escapeHtml(sourceInfo)}
      </div>
    </div>
    <div class="video-cursor-bar">
      <span><strong>Source:</strong> ${escapeHtml(sourceInfo)}</span>
      <span>${latestObs ? 'Latest Frame Sampled' : 'Standby'}</span>
    </div>
    <div style="margin-top: var(--space-4);">
      <div style="display: flex; justify-content: space-between; align-items: center; gap: var(--space-3); flex-wrap: wrap;">
        <button id="btn-run-observation" class="btn btn-primary" style="font-size: 0.85rem;">
          ⚡ Run observation now
        </button>
        <span style="font-size: 0.75rem; color: var(--color-text-muted);">
          Bounded autonomous execution (1 sample)
        </span>
      </div>
      <div id="observation-action-status" style="display: none;"></div>
    </div>
  `;

  // Fallback if video is absent
  const videoEl = card.querySelector('video');
  videoEl.addEventListener('error', () => {
    const container = card.querySelector('.video-container');
    container.innerHTML = `
      <div class="video-placeholder">
        <div class="video-placeholder-icon">📷</div>
        <strong style="color: #F1F4F7;">Demo Video Standby</strong>
        <p style="font-size: 0.75rem; color: #A0B0C0; max-width: 320px;">
          Local video file not found on server or private Cloud Storage source configured. Frame provenance is preserved in observation records.
        </p>
      </div>
    `;
  });

  // Action Button Wiring with duplicate prevention and safe state lifecycle
  const runBtn = card.querySelector('#btn-run-observation');
  const statusEl = card.querySelector('#observation-action-status');

  if (runBtn) {
    let isExecuting = false;

    runBtn.addEventListener('click', async () => {
      if (isExecuting) return;
      isExecuting = true;

      // 1. Running State (Prevent duplicate clicks)
      runBtn.disabled = true;
      runBtn.classList.add('btn-disabled');
      runBtn.innerHTML = '⏳ Running observation...';

      if (statusEl) {
        statusEl.style.display = 'flex';
        statusEl.className = 'action-status status-running';
        statusEl.textContent = '⏳ Executing bounded observation cycle (Gemini visual analysis)...';
      }

      try {
        const response = await api.runNextWindow(animalId, 1);

        // 2. Success State
        if (statusEl) {
          statusEl.className = 'action-status status-success';
          const sampleCount = response && typeof response.samples_analyzed === 'number'
            ? `${response.samples_analyzed} sample`
            : 'Observation cycle';
          statusEl.textContent = `✅ ${sampleCount} completed successfully. Updating records...`;
        }

        // Refresh dashboard data
        if (typeof onRefresh === 'function') {
          setTimeout(async () => {
            await onRefresh();
          }, 800);
        }
      } catch (err) {
        // 3. Error State
        if (statusEl) {
          statusEl.className = 'action-status status-error';
          statusEl.textContent = `❌ Observation run failed: ${err.message || 'Server error'}`;
        }
      } finally {
        isExecuting = false;
        runBtn.disabled = false;
        runBtn.classList.remove('btn-disabled');
        runBtn.innerHTML = '⚡ Run observation now';
      }
    });
  }

  return card;
}

/**
 * 2. Environment Context Card (Strict Separation)
 */
function createEnvironmentCard(profile, latestObs) {
  const card = document.createElement('div');
  card.className = 'card';

  const envContext = latestObs && latestObs.environment_context;
  const directReadings = (latestObs && latestObs.direct_environment_readings) || (profile && profile.direct_environment_readings) || [];
  const missingRequests = (latestObs && latestObs.missing_direct_reading_requests) || [];

  let directHtml = '';
  if (directReadings.length > 0) {
    directHtml = directReadings.map(r => `
      <div class="env-data-item">
        <span>${escapeHtml(r.reading_type.replace(/_/g, ' '))}:</span>
        <span>${r.value} ${escapeHtml(r.unit)} <small style="color: var(--color-sage); font-weight: normal;">(Owner)</small></span>
      </div>
    `).join('');
  } else {
    directHtml = `<div class="empty-inline">No direct enclosure readings recorded.</div>`;
  }

  let outdoorHtml = '';
  if (envContext) {
    outdoorHtml = `
      <div class="env-data-item">
        <span>Outdoor Temp:</span>
        <span>${envContext.outdoor_temperature_c !== null ? envContext.outdoor_temperature_c + '°C' : 'N/A'}</span>
      </div>
      <div class="env-data-item">
        <span>Outdoor Humidity:</span>
        <span>${envContext.outdoor_humidity_percent !== null ? envContext.outdoor_humidity_percent + '%' : 'N/A'}</span>
      </div>
      <div class="env-data-item">
        <span>Condition:</span>
        <span style="text-transform: capitalize;">${escapeHtml(envContext.weather_condition || 'N/A')}</span>
      </div>
    `;
  } else {
    outdoorHtml = `<div class="empty-inline">Outdoor weather not configured (requires coordinates).</div>`;
  }

  let missingHtml = '';
  if (missingRequests.length > 0) {
    missingHtml = `
      <div style="grid-column: span 2; background-color: var(--color-amber-light); padding: var(--space-2) var(--space-3); border-radius: var(--radius-sm); border: 1px solid rgba(184, 118, 40, 0.3); font-size: 0.8rem; color: var(--color-amber-dark); margin-top: var(--space-2);">
        ⚠️ <strong>Enclosure Reading Prompt:</strong> ${escapeHtml(missingRequests.join(' '))}
      </div>
    `;
  }

  card.innerHTML = `
    <div class="card-header">
      <span class="card-title">🌡️ Environment & Enclosure Context</span>
      <span class="badge badge-neutral">${profile && profile.enclosure_type ? escapeHtml(profile.enclosure_type) : 'Aquarium'}</span>
    </div>
    <div class="env-split">
      <div class="env-column">
        <div class="env-heading">
          <span>💧 Direct Enclosure Data</span>
        </div>
        <div class="env-data-list">
          ${directHtml}
        </div>
      </div>
      <div class="env-column">
        <div class="env-heading">
          <span>⛅ Outdoor Weather Context</span>
        </div>
        <div class="env-data-list">
          ${outdoorHtml}
        </div>
      </div>
      ${missingHtml}
      <div class="env-disclaimer">
        * Outdoor weather is local ambient context only; Comfort-z never treats outdoor weather as the condition inside an enclosure.
      </div>
    </div>
  `;

  return card;
}

/**
 * 3. Budget & Cursor Card
 */
function createBudgetCard(profile, latestObs) {
  const card = document.createElement('div');
  card.className = 'card';

  if (!profile) {
    card.innerHTML = `
      <div class="card-header">
        <span class="card-title">⏱️ Autonomous Monitoring Controls</span>
        <span class="badge badge-neutral">Profile Standby</span>
      </div>
      <div class="animal-metrics" style="margin-bottom: 0;">
        <div class="metric-item">
          <span class="metric-label">Daily Sample Quota</span>
          <span class="metric-value">Not configured</span>
        </div>
        <div class="metric-item">
          <span class="metric-label">Active Sampling Interval</span>
          <span class="metric-value">Not configured</span>
        </div>
        <div class="metric-item">
          <span class="metric-label">Prerecorded Cursor</span>
          <span class="metric-value">${latestObs && latestObs.source_info ? escapeHtml(latestObs.source_info) : 'Not recorded'}</span>
        </div>
        <div class="metric-item">
          <span class="metric-label">Execution Model</span>
          <span class="metric-value">Profile required for bounded monitoring</span>
        </div>
      </div>
    `;
    return card;
  }

  const budget = profile.daily_sample_budget;
  const used = profile.samples_used_in_current_period;
  let remainingText = 'Not recorded';
  if (typeof budget === 'number' && typeof used === 'number') {
    remainingText = `${Math.max(0, budget - used)} / ${budget} remaining`;
  } else if (typeof budget === 'number') {
    remainingText = `${budget} daily budget`;
  }

  const mode = profile.current_sampling_mode || 'normal';
  const normalInterval = typeof profile.normal_sampling_interval_seconds === 'number' ? `${profile.normal_sampling_interval_seconds}s` : 'Not recorded';
  const elevatedInterval = typeof profile.elevated_sampling_interval_seconds === 'number' ? `${profile.elevated_sampling_interval_seconds}s` : 'Not recorded';
  const cursorSeconds = (typeof profile.source_cursor_seconds === 'number' && !isNaN(profile.source_cursor_seconds))
    ? `${profile.source_cursor_seconds.toFixed(2)}s`
    : 'Not recorded';
  const cursorFrame = (typeof profile.source_cursor_frame_index === 'number' && !isNaN(profile.source_cursor_frame_index))
    ? `frame ${profile.source_cursor_frame_index}`
    : 'Not recorded';

  card.innerHTML = `
    <div class="card-header">
      <span class="card-title">⏱️ Autonomous Monitoring Controls</span>
      <span class="badge ${mode === 'elevated' ? 'badge-concerning' : 'badge-normal'}">
        Mode: ${escapeHtml(mode)}
      </span>
    </div>
    <div class="animal-metrics" style="margin-bottom: 0;">
      <div class="metric-item">
        <span class="metric-label">Daily Sample Quota</span>
        <span class="metric-value">${escapeHtml(remainingText)}</span>
      </div>
      <div class="metric-item">
        <span class="metric-label">Active Sampling Interval</span>
        <span class="metric-value">${mode === 'elevated' ? escapeHtml(elevatedInterval + ' (Elevated)') : escapeHtml(normalInterval + ' (Normal)')}</span>
      </div>
      <div class="metric-item">
        <span class="metric-label">Prerecorded Cursor</span>
        <span class="metric-value">${escapeHtml(cursorSeconds)} (${escapeHtml(cursorFrame)})</span>
      </div>
      <div class="metric-item">
        <span class="metric-label">Execution Model</span>
        <span class="metric-value">Bounded Window (Cloud Run)</span>
      </div>
    </div>
  `;
  return card;
}

/**
 * 4. Latest Observation Card
 */
function createObservationCard(obs) {
  const card = document.createElement('div');
  card.className = 'card';

  if (!obs) {
    card.innerHTML = `
      <div class="card-header">
        <span class="card-title">🔍 Latest Visual Observation</span>
      </div>
      <div class="empty-inline">No observation records available yet for this animal.</div>
    `;
    return card;
  }

  const gemini = obs.gemini_observation || {};
  const isVisible = gemini.animal_visible !== false;
  const status = gemini.observation_status || (isVisible ? 'valid' : 'animal_not_visible');
  const posture = gemini.posture || 'Not specified';
  const activity = gemini.activity_level || 'unclear';
  const movement = gemini.apparent_movement || 'Not specified';
  const abnormalities = gemini.visible_abnormalities || [];
  const interpretation = gemini.behavioral_interpretation || obs.explanation || 'No interpretation provided.';
  const confidence = (typeof gemini.confidence === 'number' && !isNaN(gemini.confidence)) ? gemini.confidence : null;
  const uncertainty = gemini.uncertainty || '';
  const severityBadge = getSeverityBadge(obs.severity);

  let confidenceHtml = '';
  if (confidence !== null) {
    confidenceHtml = `
      <div class="confidence-meter">
        <div class="meter-bar">
          <div class="meter-fill" style="width: ${Math.round(confidence * 100)}%;"></div>
        </div>
        <span style="font-weight: 700; font-size: 0.85rem;">${formatConfidence(confidence)}</span>
      </div>
    `;
  } else {
    confidenceHtml = `<div class="obs-value" style="color: var(--color-text-muted); font-style: italic;">Not available</div>`;
  }

  card.innerHTML = `
    <div class="card-header">
      <span class="card-title">🔍 Latest Visual Observation</span>
      <div style="display: flex; gap: var(--space-2); align-items: center;">
        <span class="badge ${isVisible ? 'badge-normal' : 'badge-monitor'}">
          ${isVisible ? 'Animal Visible' : 'Animal Not Visible'}
        </span>
        <span class="badge ${severityBadge.class}">${severityBadge.label}</span>
      </div>
    </div>
    <div class="observation-main">
      <div style="font-size: 0.75rem; color: var(--color-text-muted);">
        Recorded: ${formatTimestamp(obs.timestamp)} | Observation ID: <code>${escapeHtml(obs.observation_id ? obs.observation_id.substring(0, 8) : 'N/A')}</code>
      </div>

      <div class="observation-row">
        <span class="obs-label">Behavioral Interpretation (Gemini)</span>
        <div class="obs-value interpretation">
          ${escapeHtml(interpretation)}
        </div>
      </div>

      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-3);">
        <div class="observation-row">
          <span class="obs-label">Observed Posture</span>
          <span class="obs-value">${escapeHtml(posture)}</span>
        </div>
        <div class="observation-row">
          <span class="obs-label">Activity Level</span>
          <span class="obs-value" style="text-transform: capitalize;">${escapeHtml(activity)}</span>
        </div>
        <div class="observation-row">
          <span class="obs-label">Apparent Movement</span>
          <span class="obs-value">${escapeHtml(movement)}</span>
        </div>
        <div class="observation-row">
          <span class="obs-label">Visible Abnormalities</span>
          <span class="obs-value">${abnormalities.length > 0 ? escapeHtml(abnormalities.join(', ')) : '<span style="color: var(--color-sage);">None visibly observed</span>'}</span>
        </div>
      </div>

      <div class="observation-row">
        <span class="obs-label">Observation Confidence & Evidence</span>
        ${confidenceHtml}
        ${uncertainty ? `<small style="color: var(--color-text-muted); font-size: 0.75rem; margin-top: 2px;">Uncertainty context: ${escapeHtml(uncertainty)}</small>` : ''}
      </div>
    </div>
  `;

  return card;
}

/**
 * 5. Trend & Decision Card
 */
function createTrendDecisionCard(obs) {
  const card = document.createElement('div');
  card.className = 'card';

  if (!obs) {
    card.innerHTML = `
      <div class="card-header">
        <span class="card-title">📈 Longitudinal Trend & Alerts</span>
      </div>
      <div class="empty-inline">No trend calculated yet.</div>
    `;
    return card;
  }

  const alertActive = obs.alert_status === true;
  const trend = obs.trend || 'unchanged';
  const trendText = getTrendLabel(trend);
  const severityBadge = getSeverityBadge(obs.severity);

  let bannerClass = 'stable';
  if (alertActive) {
    bannerClass = 'active-alert';
  } else if (obs.severity === 'monitor' || obs.severity === 'potentially_concerning') {
    bannerClass = 'monitoring';
  }

  card.innerHTML = `
    <div class="card-header">
      <span class="card-title">📈 Trend & Agent Alert Policy</span>
      <span class="badge ${severityBadge.class}">Trend: ${escapeHtml(trendText)}</span>
    </div>
    <div class="alert-banner ${bannerClass}">
      <div class="alert-title">
        <span>${alertActive ? '🚨 Alert: Potential Pattern Detected' : (obs.severity === 'monitor' ? '👁️ Monitoring Active: Cautious Baseline' : '✅ Stable: Normal Behavioral Pattern')}</span>
      </div>
      <div class="alert-text">
        ${alertActive
          ? 'Potentially concerning visible patterns were identified across recent observations. Comfort-z recommends seeking professional veterinary advice.'
          : (obs.severity === 'monitor'
            ? 'Observation saved to history. Comfort-z continues monitoring without requiring manual prompts.'
            : 'Visible activity and posture align with normal expected behavior. Observation persisted for long-term baseline comparison.')}
      </div>
      <div class="alert-action">
        <strong>Recommended Next Step:</strong> ${alertActive ? 'Seek professional veterinary guidance if behavior persists.' : 'Continue bounded autonomous monitoring.'}
      </div>
    </div>
  `;

  return card;
}

/**
 * 6. Conditional Research Findings Card
 */
function createResearchCard(obs) {
  const card = document.createElement('div');
  card.className = 'card research-card';

  const research = obs && obs.research_context;
  if (!research || (!research.result && !research.decision)) {
    card.innerHTML = `
      <div class="card-header">
        <span class="card-title">📚 Conditional Grounded Research</span>
        <span class="badge badge-neutral">Standby</span>
      </div>
      <div class="empty-inline">
        Research remains dormant during normal observations. Comfort-z conditionally triggers Gemini Search Grounding only when worsening, recurring, or alerting patterns are detected.
      </div>
    `;
    return card;
  }

  const decision = research.decision || {};
  const result = research.result;
  const failure = research.failure;

  if (result) {
    const sourcesHtml = (result.sources || []).map(s => `
      <div class="source-item">
        <div class="source-header">
          <a class="source-title" href="${escapeHtml(s.reference)}" target="_blank" rel="noopener noreferrer">${escapeHtml(s.title || s.source_name || 'Source citation')}</a>
          <span class="source-badge ${escapeHtml(s.category)}">${escapeHtml(s.category || 'unknown')}</span>
        </div>
        <div class="source-evidence">${escapeHtml(s.evidence || '')}</div>
      </div>
    `).join('');

    card.innerHTML = `
      <div class="card-header">
        <span class="card-title">📚 Grounded Research Findings</span>
        <span class="badge badge-normal">Grounding Active</span>
      </div>
      <div class="research-query">
        <strong>Query:</strong> ${escapeHtml(result.query)}
      </div>
      <div style="font-size: 0.85rem; margin-bottom: var(--space-3);">
        <strong>Authoritative Synthesis:</strong> ${escapeHtml(result.evidence_summary)}
      </div>
      ${result.community_summary && !result.community_summary.includes('No community') ? `
        <div style="font-size: 0.8rem; color: var(--color-amber-dark); background-color: var(--color-amber-light); padding: var(--space-2) var(--space-3); border-radius: var(--radius-sm); margin-bottom: var(--space-3);">
          <strong>Community Anecdote Flag:</strong> ${escapeHtml(result.community_summary)}
        </div>
      ` : ''}
      <div style="font-size: 0.75rem; color: var(--color-text-muted); margin-bottom: var(--space-2);">
        <strong>Sources & Citations:</strong>
      </div>
      <div class="research-sources-list">
        ${sourcesHtml}
      </div>
    `;
  } else if (failure) {
    card.innerHTML = `
      <div class="card-header">
        <span class="card-title">📚 Conditional Grounded Research</span>
        <span class="badge badge-neutral">Evaluated</span>
      </div>
      <div style="font-size: 0.85rem; color: var(--color-text-secondary); line-height: 1.4;">
        ${escapeHtml(failure)}
      </div>
    `;
  } else {
    card.innerHTML = `
      <div class="card-header">
        <span class="card-title">📚 Conditional Grounded Research</span>
        <span class="badge badge-neutral">Evaluated</span>
      </div>
      <div style="font-size: 0.85rem; color: var(--color-text-secondary);">
        <strong>Decision:</strong> ${escapeHtml(decision.reason || 'External research not warranted for this observation.')}
      </div>
    `;
  }

  return card;
}

/**
 * 7. History Timeline
 */
function createTimelineCard(observations) {
  const card = document.createElement('div');
  card.className = 'card';

  card.innerHTML = `
    <div class="card-header">
      <span class="card-title">🕒 Observation History</span>
      <span class="badge badge-neutral">${observations.length} Recorded</span>
    </div>
  `;

  if (observations.length === 0) {
    const empty = document.createElement('div');
    empty.className = 'empty-inline';
    empty.textContent = 'No past observations found.';
    card.appendChild(empty);
    return card;
  }

  const timeline = document.createElement('div');
  timeline.className = 'timeline';

  observations.forEach(item => {
    const gemini = item.gemini_observation || {};
    const severityBadge = getSeverityBadge(item.severity);
    const itemEl = document.createElement('div');
    itemEl.className = 'timeline-item';
    itemEl.innerHTML = `
      <div class="timeline-time">${formatTimestamp(item.timestamp)}</div>
      <div class="timeline-content">
        <div style="display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 2px;">
          <strong style="font-size: 0.85rem; text-transform: capitalize;">${escapeHtml(gemini.posture || 'Observation')}</strong>
          <span class="badge ${severityBadge.class}">${severityBadge.label}</span>
        </div>
        <p style="font-size: 0.8rem; color: var(--color-text-secondary); line-height: 1.35;">
          ${escapeHtml(gemini.behavioral_interpretation || item.explanation || '')}
        </p>
        <small style="color: var(--color-text-muted); font-size: 0.7rem; font-family: var(--font-mono);">
          ${escapeHtml(item.source_info || '')}
        </small>
      </div>
    `;
    timeline.appendChild(itemEl);
  });

  card.appendChild(timeline);
  return card;
}

/**
 * 8. Daily Reports Card
 */
function createReportsCard(animalId, reports, onRefresh) {
  const card = document.createElement('div');
  card.className = 'card';

  card.innerHTML = `
    <div class="card-header">
      <span class="card-title">📋 Daily Summaries & 24h Reports</span>
      <span class="badge badge-neutral">${reports.length} Available</span>
    </div>
    <div style="margin-bottom: var(--space-4);">
      <div style="display: flex; justify-content: space-between; align-items: center; gap: var(--space-3); flex-wrap: wrap;">
        <button id="btn-generate-report" class="btn btn-secondary" style="font-size: 0.85rem;">
          📑 Generate daily report
        </button>
        <span style="font-size: 0.75rem; color: var(--color-text-muted);">
          Synthesizes 24h structured history
        </span>
      </div>
      <div id="report-action-status" style="display: none;"></div>
    </div>
  `;

  if (reports.length === 0) {
    const empty = document.createElement('div');
    empty.className = 'empty-inline';
    empty.innerHTML = `No daily reports generated yet. Reports are synthesized from persisted structured history only.`;
    card.appendChild(empty);
  } else {
    const list = document.createElement('div');
    list.style.display = 'flex';
    list.style.flexDirection = 'column';
    list.style.gap = 'var(--space-3)';

    reports.forEach(r => {
      const rEl = document.createElement('div');
      rEl.className = 'source-item';
      const narrative = r.narrative || {};
      rEl.innerHTML = `
        <div style="font-size: 0.85rem; font-weight: 700; color: var(--color-primary-dark); margin-bottom: 4px;">
          Report for ${formatTimestamp(r.generated_at)}
        </div>
        <div style="font-size: 0.8rem; color: var(--color-text-secondary); line-height: 1.4;">
          <strong>Activity & Behavior:</strong> ${escapeHtml(narrative.overall_activity_behavior || 'Summary available in record.')}
        </div>
        <div style="font-size: 0.75rem; color: var(--color-text-muted); margin-top: 4px;">
          Valid frames: ${r.valid_observation_count || 0} | Concerning: ${(r.concerning_observation_ids || []).length} | Alerts: ${(r.alert_observation_ids || []).length}
        </div>
      `;
      list.appendChild(rEl);
    });

    card.appendChild(list);
  }

  // Action Button Wiring with duplicate prevention and safe state lifecycle
  const generateBtn = card.querySelector('#btn-generate-report');
  const statusEl = card.querySelector('#report-action-status');

  if (generateBtn) {
    let isGenerating = false;

    generateBtn.addEventListener('click', async () => {
      if (isGenerating) return;
      isGenerating = true;

      // 1. Generating State (Prevent duplicate clicks)
      generateBtn.disabled = true;
      generateBtn.classList.add('btn-disabled');
      generateBtn.innerHTML = '⏳ Generating report...';

      if (statusEl) {
        statusEl.style.display = 'flex';
        statusEl.className = 'action-status status-running';
        statusEl.textContent = '⏳ Synthesizing daily monitoring report from persisted observation history...';
      }

      try {
        const response = await api.generateDailyReport(animalId);

        // 2. Success State
        if (statusEl) {
          statusEl.className = 'action-status status-success';
          const reportId = response && response.report_id ? `Report ${response.report_id.substring(0, 8)}` : 'Daily report';
          statusEl.textContent = `✅ ${reportId} generated successfully. Updating records...`;
        }

        // Refresh dashboard data
        if (typeof onRefresh === 'function') {
          setTimeout(async () => {
            await onRefresh();
          }, 800);
        }
      } catch (err) {
        // 3. Error State
        if (statusEl) {
          statusEl.className = 'action-status status-error';
          statusEl.textContent = `❌ Report generation failed: ${err.message || 'Server error'}`;
        }
      } finally {
        isGenerating = false;
        generateBtn.disabled = false;
        generateBtn.classList.remove('btn-disabled');
        generateBtn.innerHTML = '📑 Generate daily report';
      }
    });
  }

  return card;
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
