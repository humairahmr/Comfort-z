/**
 * Animals Overview Component
 * Renders the top-level monitoring overview with honest state representation.
 */

import { getSeverityBadge, formatTimestamp } from '../state.js';

export function renderOverview(animals, navigate) {
  const container = document.createElement('div');
  container.className = 'overview-container';

  // 10-Second Explainer Mission Banner
  const banner = document.createElement('div');
  banner.className = 'explainer-banner';
  banner.innerHTML = `
    <div class="explainer-icon">🌿</div>
    <div class="explainer-body">
      <h2>Autonomous Animal Care Monitoring</h2>
      <p>Comfort-z watches an animal autonomously, remembers what it observes, compares behaviour over time, decides when something matters, researches when necessary, and alerts the owner without requiring a new prompt for every observation.</p>
    </div>
  `;
  container.appendChild(banner);

  // Section Header
  const header = document.createElement('div');
  header.className = 'animals-section-header';
  header.innerHTML = `
    <h2>Your Monitored Animals</h2>
    <span class="metric-label">${animals.length} configured ${animals.length === 1 ? 'profile' : 'profiles'}</span>
  `;
  container.appendChild(header);

  // Grid
  const grid = document.createElement('div');
  grid.className = 'animals-grid';

  // If there are real saved backend profiles, render them
  if (animals.length > 0) {
    animals.forEach(profile => {
      const card = createAnimalCard(profile, navigate);
      grid.appendChild(card);
    });
  } else {
    const emptyBox = document.createElement('div');
    emptyBox.className = 'state-box';
    emptyBox.style.gridColumn = '1 / -1';
    emptyBox.innerHTML = `
      <div class="state-icon">🐾</div>
      <h3>No monitored animals yet</h3>
      <p>An animal monitoring profile must be configured before autonomous monitoring begins. Saved profiles will appear here.</p>
    `;
    grid.appendChild(emptyBox);
  }

  // Multi-animal architectural preview card (Clearly labeled as preview)
  const previewCard = document.createElement('div');
  previewCard.className = 'card animal-card';
  previewCard.style.opacity = '0.9';
  previewCard.style.borderStyle = 'dashed';
  previewCard.innerHTML = `
    <div class="animal-card-top">
      <div>
        <span class="preview-banner-tag">Architectural Preview</span>
        <div class="animal-name">Gendut</div>
        <div class="animal-species">Domestic Cat (Felis catus)</div>
      </div>
      <span class="badge badge-neutral">Standby</span>
    </div>
    <div class="animal-goal">
      <strong>Monitoring Goal:</strong> Monitor mobility and resting posture in living room.
    </div>
    <div class="animal-metrics">
      <div class="metric-item">
        <span class="metric-label">Enclosure</span>
        <span class="metric-value">Indoor Home</span>
      </div>
      <div class="metric-item">
        <span class="metric-label">Source</span>
        <span class="metric-value">Living Room Cam</span>
      </div>
    </div>
    <p class="preview-notice">
      Demonstrates multi-animal system architecture. Behavioural analysis has been demonstrated and tested on Raku.
    </p>
    <div class="animal-card-footer">
      <span class="metric-label">Multi-Animal Ready</span>
      <span class="card-action-link" style="color: var(--color-text-muted);">Preview Only</span>
    </div>
  `;
  grid.appendChild(previewCard);

  // Add Animal Placeholder Card (Read-only for this pass)
  const addCard = document.createElement('div');
  addCard.className = 'card';
  addCard.style.display = 'flex';
  addCard.style.flexDirection = 'column';
  addCard.style.alignItems = 'center';
  addCard.style.justifyContent = 'center';
  addCard.style.textAlign = 'center';
  addCard.style.borderStyle = 'dashed';
  addCard.style.backgroundColor = 'var(--color-bg-subtle)';
  addCard.style.padding = 'var(--space-6)';
  addCard.innerHTML = `
    <div style="font-size: 1.8rem; margin-bottom: var(--space-2); color: var(--color-primary);">➕</div>
    <h3 style="font-size: 1rem; font-weight: 700; color: var(--color-primary-dark); margin-bottom: 4px;">Add New Animal</h3>
    <p style="font-size: 0.8rem; color: var(--color-text-muted); margin-bottom: var(--space-4);">Configure a bounded autonomous monitoring profile for another animal.</p>
    <span class="btn btn-secondary btn-disabled" style="font-size: 0.75rem;">Add Profile (Read-only Pass)</span>
  `;
  grid.appendChild(addCard);

  container.appendChild(grid);
  return container;
}

function createAnimalCard(profile, navigate) {
  const card = document.createElement('div');
  card.className = 'card animal-card';

  const animalId = profile.animal_id || 'Unknown';
  const name = profile.animal_name || animalId;
  const species = profile.expected_species || 'Species not specified';
  const goal = profile.monitoring_goal || 'No specific monitoring goal saved.';
  const mode = profile.current_sampling_mode || 'normal';
  const used = profile.samples_used_in_current_period || 0;
  const budget = profile.daily_sample_budget || 24;
  const remaining = Math.max(0, budget - used);
  const active = profile.active !== false;

  card.innerHTML = `
    <div class="animal-card-top">
      <div>
        <div class="animal-name">${escapeHtml(name)}</div>
        <div class="animal-species">${escapeHtml(species)}</div>
      </div>
      <span class="badge ${active ? 'badge-normal' : 'badge-neutral'}">
        ${active ? 'Monitoring Active' : 'Inactive'}
      </span>
    </div>
    <div class="animal-goal">
      <strong>Goal:</strong> ${escapeHtml(goal)}
    </div>
    <div class="animal-metrics">
      <div class="metric-item">
        <span class="metric-label">Sampling Mode</span>
        <span class="metric-value" style="text-transform: capitalize;">${escapeHtml(mode)}</span>
      </div>
      <div class="metric-item">
        <span class="metric-label">Daily Budget</span>
        <span class="metric-value">${remaining} / ${budget} remaining</span>
      </div>
      <div class="metric-item">
        <span class="metric-label">Source Type</span>
        <span class="metric-value" style="text-transform: capitalize;">${escapeHtml(profile.source_type || 'video')}</span>
      </div>
      <div class="metric-item">
        <span class="metric-label">Last Checked</span>
        <span class="metric-value">${profile.last_monitoring_run ? formatTimestamp(profile.last_monitoring_run) : 'Not yet run'}</span>
      </div>
    </div>
    <div class="animal-card-footer">
      <span class="metric-label">ID: ${escapeHtml(animalId)}</span>
      <span class="card-action-link">Open Dashboard →</span>
    </div>
  `;

  card.addEventListener('click', () => navigate(`#/animals/${encodeURIComponent(animalId)}`));
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
