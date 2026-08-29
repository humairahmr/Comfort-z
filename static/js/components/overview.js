/** Overview: real monitoring profiles with decorative, local profile fallbacks. */

import { formatTimestamp } from '../state.js';
import { renderAnimalVisual } from './silhouettes.js';

export function renderOverview(animals, navigate) {
  const container = document.createElement('div');
  container.className = 'overview-container';
  const activeAnimal = animals.find((animal) => animal.active !== false) || animals[0] || null;

  const heading = document.createElement('header');
  heading.className = 'overview-heading';
  heading.innerHTML = `
    <div>
      <h1>Overview</h1>
      <p>Longitudinal monitoring, presented with the context needed for careful care.</p>
    </div>
    <span class="overview-live-state"><span></span> ${activeAnimal ? 'Monitoring profiles loaded' : 'No profile configured'}</span>
  `;
  container.appendChild(heading);

  if (activeAnimal) {
    container.appendChild(createHero(activeAnimal, navigate));
  } else {
    const empty = document.createElement('section');
    empty.className = 'overview-empty-state';
    empty.innerHTML = '<h2>No monitored animals yet</h2><p>Create a monitoring profile through the existing API to see it here.</p>';
    container.appendChild(empty);
  }

  container.appendChild(createAnimalsSection(animals, navigate));
  return container;
}

export function renderAllAnimals(animals, navigate) {
  const container = document.createElement('div');
  container.className = 'overview-container all-animals-container';

  const heading = document.createElement('header');
  heading.className = 'overview-heading';
  heading.innerHTML = `
    <div>
      <h1>All Animals</h1>
      <p>Configured monitoring profiles and their current status.</p>
    </div>
    <span class="overview-live-state"><span></span> ${animals.length} ${animals.length === 1 ? 'profile' : 'profiles'} loaded</span>
  `;
  container.appendChild(heading);
  container.appendChild(createAnimalsSection(animals, navigate, { includePrototypeCards: false }));
  return container;
}

function createAnimalsSection(animals, navigate, { includePrototypeCards = true } = {}) {
  const section = document.createElement('section');
  section.className = 'animals-section';
  if (!includePrototypeCards && animals.length === 1) {
    section.classList.add('animals-section--single-profile');
  }
  section.innerHTML = '<div class="animals-section-heading"><h2>My Animals</h2><p>Only configured profiles are shown here.</p></div>';
  const grid = document.createElement('div');
  grid.className = 'animal-card-grid';
  animals.forEach((animal) => grid.appendChild(createAnimalCard(animal, navigate)));
  if (includePrototypeCards) {
    grid.appendChild(createPreviewCard());
    grid.appendChild(createAddAnimalCard());
  }
  section.appendChild(grid);
  return section;
}

function createHero(profile, navigate) {
  const name = profile.animal_name || profile.animal_id;
  const species = profile.expected_species || 'Species not recorded';
  const remaining = Math.max(0, (profile.daily_sample_budget || 0) - (profile.samples_used_in_current_period || 0));
  const hero = document.createElement('article');
  hero.className = 'animal-hero';
  hero.tabIndex = 0;
  hero.setAttribute('aria-label', `Open monitoring console for ${name}`);
  hero.innerHTML = `
    <div class="animal-hero-visual-wrap">
      ${renderAnimalVisual(profile, { className: 'animal-hero-visual', alt: `Profile of ${name}` })}
      <span class="visual-disclaimer">Decorative profile fallback</span>
    </div>
    <div class="animal-hero-copy">
      <div class="animal-hero-status"><span class="status-orb ${profile.active === false ? 'is-idle' : ''}"></span>${profile.active === false ? 'Monitoring inactive' : 'Monitoring active'}</div>
      <h2>${escapeHtml(name)}</h2>
      <p class="animal-hero-species">${escapeHtml(species)}</p>
      <p class="animal-hero-goal">${escapeHtml(profile.monitoring_goal || 'Monitoring goal not recorded.')}</p>
      <div class="animal-hero-telemetry" aria-label="Monitoring profile telemetry">
        <span><b>Last run</b>${profile.last_monitoring_run ? escapeHtml(formatTimestamp(profile.last_monitoring_run)) : 'Not yet run'}</span>
        <span><b>Mode</b>${escapeHtml(profile.current_sampling_mode || 'Not recorded')}</span>
        <span><b>Budget</b>${profile.daily_sample_budget ? `${remaining} of ${profile.daily_sample_budget} left` : 'Not recorded'}</span>
        <span><b>Source</b>${escapeHtml(sourceLabel(profile))}</span>
      </div>
      <button class="btn btn-primary hero-console-button">Open monitoring console <span aria-hidden="true">→</span></button>
    </div>
  `;
  const open = () => navigate(`#/animals/${encodeURIComponent(profile.animal_id)}`);
  hero.addEventListener('click', open);
  hero.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      open();
    }
  });
  hero.querySelector('button').addEventListener('click', (event) => {
    event.stopPropagation();
    open();
  });
  return hero;
}

function createAnimalCard(profile, navigate) {
  const name = profile.animal_name || profile.animal_id;
  const card = document.createElement('article');
  card.className = 'animal-card';
  card.tabIndex = 0;
  card.innerHTML = `
    <div class="animal-card-visual">${renderAnimalVisual(profile, { className: 'animal-card-silhouette', alt: `Profile of ${name}` })}</div>
    <div class="animal-card-content">
      <span class="animal-card-status"><span class="status-orb ${profile.active === false ? 'is-idle' : ''}"></span>${profile.active === false ? 'Inactive' : 'Monitoring active'}</span>
      <h3>${escapeHtml(name)}</h3>
      <p>${escapeHtml(profile.expected_species || 'Species not recorded')}</p>
      <div class="animal-card-footer">
        <small>${profile.last_monitoring_run ? `Latest: ${escapeHtml(formatTimestamp(profile.last_monitoring_run))}` : 'No monitoring run recorded'}</small>
        <span class="animal-card-arrow" aria-hidden="true">→</span>
      </div>
    </div>
  `;
  const open = () => navigate(`#/animals/${encodeURIComponent(profile.animal_id)}`);
  card.addEventListener('click', open);
  card.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      open();
    }
  });
  return card;
}

function createPreviewCard() {
  const card = document.createElement('article');
  card.className = 'animal-card animal-card-preview';
  card.setAttribute('aria-label', 'Gendut architectural preview profile');
  card.innerHTML = `
    <div class="animal-card-visual">${renderAnimalVisual({ expected_species: 'Domestic cat' }, { className: 'animal-card-silhouette', alt: '' })}</div>
    <div class="animal-card-content">
      <span class="animal-card-status preview-status">Preview profile</span>
      <h3>Gendut</h3>
      <p>Domestic cat</p>
      <small>Architectural preview only — not actively monitored.</small>
    </div>
  `;
  return card;
}

function createAddAnimalCard() {
  const card = document.createElement('article');
  card.className = 'add-animal-card';
  card.setAttribute('aria-disabled', 'true');
  card.innerHTML = `
    <span class="add-animal-icon" aria-hidden="true">+</span>
    <h3>Add Animal</h3>
    <p>Profile setup is not configured in this console yet.</p>
    <span class="add-animal-state">Coming later</span>
  `;
  return card;
}

function sourceLabel(profile) {
  if (profile.source_type === 'webcam') return 'Live webcam';
  if (String(profile.source_reference || '').startsWith('gs://')) return 'Cloud video';
  if (profile.source_type === 'video') return 'Local video';
  return 'Source not recorded';
}

function escapeHtml(value) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
