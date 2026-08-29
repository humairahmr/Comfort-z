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
import { renderAnimalVisual } from './silhouettes.js';

export function renderDashboard(animalId, profile, observations, reports, navigate, onRefresh) {
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

  // 3. Editorial Console Workspace
  const consoleLayout = document.createElement('div');
  consoleLayout.className = 'console-dashboard';

  // Section 1: The Unified Observation Stage (Dark Primary Visual Anchor - Preserved)
  consoleLayout.appendChild(createObservationStage(animalId, profile, latestObs, onRefresh));

  // Section 2: Full-Width Dual-Context Environmental Reasoning Ribbon (No Boxy Cards)
  consoleLayout.appendChild(createTelemetryRibbon(profile, latestObs));

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
  intelRight.appendChild(createReportsModule(animalId, reports, onRefresh));
  intelRight.appendChild(createTimelineModule(observations));
  intelLayout.appendChild(intelRight);

  consoleLayout.appendChild(intelLayout);

  // Section 4: Compact Footer Diagnostics Ribbon
  consoleLayout.appendChild(createDiagnosticsRibbon(profile, latestObs));

  container.appendChild(consoleLayout);
  return container;
}

/**
 * 0. Editorial Animal Profile Hero
 */
function createAnimalHero(animalId, profile, latestObs) {
  const hero = document.createElement('section');
  hero.className = 'animal-identity-hero';
  hero.setAttribute('aria-label', 'Animal Identity Profile');

  const name = (profile && profile.animal_name) || (latestObs && latestObs.animal_name) || animalId;
  const species = (profile && profile.expected_species) || (latestObs && latestObs.expected_species) || 'Species not specified';
  const goal = (profile && profile.monitoring_goal) || 'Continuous welfare monitoring for ' + name;
  const active = profile ? profile.active !== false : true;
  const mode = profile ? profile.current_sampling_mode || 'normal' : 'normal';
  const used = profile ? profile.samples_used_in_current_period || 0 : (latestObs ? 1 : 0);
  const budget = profile ? profile.daily_sample_budget || 24 : 24;
  const remaining = Math.max(0, budget - used);

  // Format source type clearly
  let sourceLabel = 'Prerecorded Video Feed';
  if (profile && profile.source_type === 'webcam') {
    sourceLabel = 'Live Camera Feed';
  } else if (profile && String(profile.source_reference).startsWith('gs://')) {
    sourceLabel = 'Cloud Video Feed';
  }

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

  const photoHtml = renderAnimalVisual(
    profile || { expected_species: species },
    { className: 'hero-profile-visual', alt: `Profile of ${name}` }
  );

  hero.innerHTML = `
    <div class="hero-identity-main">
      <div class="hero-status-row">
        <span class="badge ${active ? 'badge-normal' : 'badge-neutral'}">
          <span class="badge-dot"></span>
          ${active ? 'Continuous Monitoring Active' : 'Profile Inactive'}
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

    <div class="hero-portrait-frame">
      ${photoHtml}
      <span class="hero-silhouette-caption">Decorative profile fallback</span>
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

  const sourceInfo = (profile && profile.source_reference) || (latestObs && latestObs.source_info) || 'Visual feed not specified';
  
  let sourceBadge = 'Prerecorded Video Feed';
  if (profile && profile.source_type === 'webcam') {
    sourceBadge = 'Live Camera Feed';
  } else if (String(sourceInfo).startsWith('gs://')) {
    sourceBadge = 'Cloud Video Feed';
  }

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
      <span>${latestObs ? 'Sampled: ' + formatTimestamp(latestObs.timestamp) : 'Awaiting observation cycle'}</span>
    </div>
  `;
  stage.appendChild(topBar);

  // Main Viewport Split
  const viewportSplit = document.createElement('div');
  viewportSplit.className = 'stage-viewport-split';

  // Left Pane: Media Frame
  const mediaPane = document.createElement('div');
  mediaPane.className = 'stage-media-pane';
  mediaPane.innerHTML = `
    <div class="stage-video-frame">
      <video class="stage-video-player" controls muted preload="metadata" playsinline>
        <source src="/demo-video/raku.mp4" type="video/mp4">
        Your browser does not support video playback.
      </video>
      <div class="stage-source-badge">
        <span class="badge-dot" style="background-color: var(--color-peach);"></span>
        <span>${escapeHtml(sourceBadge)}</span>
      </div>
    </div>
  `;

  const videoEl = mediaPane.querySelector('video');
  videoEl.addEventListener('error', () => {
    const frame = mediaPane.querySelector('.stage-video-frame');
    frame.innerHTML = `
      <div class="stage-placeholder">
        <h3>Visual Feed Connected</h3>
        <p style="font-size: var(--font-size-body); max-width: 340px; margin: 0 auto; line-height: 1.5;">
          Cloud Storage source active. Bounded frame extraction and multimodal inference operate on stored media.
        </p>
      </div>
    `;
  });
  viewportSplit.appendChild(mediaPane);

  // Right Pane: Live Behavioral Telemetry & Gemini Synthesis
  const telemetryPane = document.createElement('div');
  telemetryPane.className = 'stage-telemetry-pane';

  if (!latestObs) {
    telemetryPane.innerHTML = `
      <div class="stage-telemetry-header">
        <span class="stage-telemetry-title">Live Telemetry</span>
        <span class="badge badge-stage-monitor">Awaiting Observation</span>
      </div>
      <p style="color: var(--color-stage-text-subtle); font-size: var(--font-size-body); line-height: 1.5;">
        No visual observation records saved yet. Click "Run observation now" below to sample the current frame.
      </p>
    `;
  } else {
    telemetryPane.innerHTML = `
      <div>
        <div class="stage-telemetry-header">
          <span class="stage-telemetry-title">Behavioral Synthesis</span>
          <span class="badge badge-stage-${severity}">
            <span class="badge-dot"></span>
            ${escapeHtml(gemini.observation_status || severity)} • ${isVisible ? 'Animal Visible' : 'Animal Not Visible'}
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
  bottomBar.innerHTML = `
    <div style="display: flex; align-items: center; gap: var(--space-4); flex-wrap: wrap;">
      <button id="btn-run-observation" class="btn btn-stage-primary">
        Run observation now
      </button>
      <div id="stage-action-status" style="display: none;" role="status" aria-live="polite"></div>
    </div>
    <div style="font-size: var(--font-size-label); color: var(--color-stage-text-muted); font-family: var(--font-mono);">
      <span>${escapeHtml(sourceInfo)}</span>
    </div>
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
function createTelemetryRibbon(profile, latestObs) {
  const ribbon = document.createElement('section');
  ribbon.className = 'telemetry-ribbon';
  ribbon.setAttribute('aria-label', 'Environmental Telemetry Context');

  const readings = (latestObs && latestObs.direct_environment_readings) ||
                   (profile && profile.direct_environment_readings) || [];

  const envContext = latestObs && latestObs.environment_context;
  const locationName = (envContext && envContext.location_name) || (profile && profile.location_name) || 'Location not recorded';
  const outdoorTemp = envContext && envContext.outdoor_temperature_c != null ? envContext.outdoor_temperature_c + '°C' : 'Not recorded';
  const outdoorHum = envContext && envContext.outdoor_humidity_percent != null ? envContext.outdoor_humidity_percent + '%' : 'Not recorded';
  const weatherCond = envContext && envContext.weather_condition ? envContext.weather_condition : 'Not recorded';

  // Left Half: Ambient Outdoor Weather (Step 1 in Reasoning Chain)
  const halfOutdoor = document.createElement('div');
  halfOutdoor.className = 'telemetry-strip-half';
  halfOutdoor.innerHTML = `
    <div class="ribbon-header" style="color: var(--color-primary);">
      <span class="badge-dot" style="background-color: var(--color-primary);"></span>
      <span>1. Ambient Meteorological Context (${escapeHtml(locationName)})</span>
    </div>
    <div style="display: flex; align-items: baseline; gap: var(--space-3);">
      <span class="ribbon-value-lead">${escapeHtml(outdoorTemp)}</span>
      <span class="ribbon-sub-metric" style="text-transform: capitalize;">${escapeHtml(weatherCond)} • ${escapeHtml(outdoorHum)} humidity</span>
    </div>
    <div class="ribbon-reasoning-flow">
      <strong>Environmental Context:</strong> Ambient outdoor conditions inform baseline thermal exposure and seasonal behavioral expectations.
    </div>
    <p class="ribbon-provenance-caption">
      OPEN-METEO METEOROLOGICAL CONTEXT • NOT AN ENCLOSURE SENSOR READING
    </p>
  `;
  ribbon.appendChild(halfOutdoor);

  // Right Half: Direct Enclosure Telemetry (Step 2 in Reasoning Chain)
  const halfEnclosure = document.createElement('div');
  halfEnclosure.className = 'telemetry-strip-half';

  let enclosureValueHtml = '';
  if (readings.length > 0) {
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

  const missingReq = (latestObs && latestObs.missing_direct_reading_requests && latestObs.missing_direct_reading_requests[0]) || '';

  halfEnclosure.innerHTML = `
    <div class="ribbon-header" style="color: var(--color-secondary);">
      <span class="badge-dot" style="background-color: var(--color-secondary);"></span>
      <span>2. Direct Enclosure Telemetry (${escapeHtml((profile && profile.enclosure_type) || 'Type not recorded')})</span>
    </div>
    ${enclosureValueHtml}
    <div class="ribbon-reasoning-flow">
      ${missingReq ? `<strong>Sensor Advisory:</strong> ${escapeHtml(missingReq)}` : `<strong>Enclosure Assessment:</strong> No owner-provided enclosure reading is available.`}
    </div>
    <p class="ribbon-provenance-caption">
      Direct physical telemetry from inside the animal's enclosure.
    </p>
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
function createReportsModule(animalId, reports, onRefresh) {
  const module = document.createElement('section');
  module.className = 'editorial-open-section';

  const header = document.createElement('div');
  header.className = 'editorial-section-header';
  header.innerHTML = `
    <h3 class="editorial-section-title">Daily Care Summaries</h3>
    <span class="editorial-section-meta">${reports.length} Synthesized</span>
  `;
  module.appendChild(header);

  // Action Strip
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
