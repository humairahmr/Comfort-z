/** Overview: real monitoring profiles with decorative, local profile fallbacks. */

import { formatTimestamp } from '../state.js';
import { renderAnimalVisual } from './silhouettes.js';
import {
  hasMonitoringSource,
  monitoringDisplayPriority,
  monitoringStatusClass,
  monitoringStatusText,
  profileSpeciesLabel,
  sourceDisplayLabel,
} from './monitoring-state.mjs';

export function renderOverview(animals, navigate) {
  const container = document.createElement('div');
  container.className = 'overview-container';
  const orderedAnimals = orderAnimalsForDisplay(animals);
  const activeAnimal = orderedAnimals.find((animal) => hasMonitoringSource(animal) && animal.active !== false) || orderedAnimals[0] || null;

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

  container.appendChild(createAnimalsSection(orderedAnimals, navigate));
  return container;
}

export function renderAllAnimals(animals, navigate) {
  const container = document.createElement('div');
  container.className = 'overview-container all-animals-container';
  const orderedAnimals = orderAnimalsForDisplay(animals);

  const heading = document.createElement('header');
  heading.className = 'overview-heading';
  heading.innerHTML = `
    <div>
      <h1>All Animals</h1>
      <p>Configured monitoring profiles and their current status.</p>
    </div>
    <div class="all-animals-heading-actions">
      <span class="overview-live-state"><span></span> ${animals.length} ${animals.length === 1 ? 'profile' : 'profiles'} loaded</span>
      <a class="all-animals-add-action" href="#/animals/new">
        <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 5v14M5 12h14" /></svg>
        <span>Add animal</span>
      </a>
    </div>
  `;
  container.appendChild(heading);
  container.appendChild(createAnimalsSection(orderedAnimals, navigate, { includeAddAnimal: false }));
  return container;
}

export function renderMonitoringPage(animals, navigate) {
  const container = document.createElement('div');
  container.className = 'overview-container monitoring-container';
  const orderedAnimals = orderAnimalsForDisplay(animals);
  const heading = document.createElement('header');
  heading.className = 'overview-heading';
  heading.innerHTML = `
    <div>
      <h1>Monitoring</h1>
      <p>Source status and bounded monitoring controls for configured animals.</p>
    </div>
    <span class="overview-live-state"><span></span> ${orderedAnimals.length} ${orderedAnimals.length === 1 ? 'profile' : 'profiles'} configured</span>
  `;
  container.appendChild(heading);
  const list = document.createElement('section');
  list.className = 'monitoring-profile-list';
  if (!orderedAnimals.length) {
    list.innerHTML = '<p class="empty-inline">No animal profiles are configured yet.</p>';
  } else {
    orderedAnimals.forEach((profile) => {
      const name = profile.animal_name || profile.animal_id;
      const item = document.createElement('article');
      item.className = 'monitoring-profile-row';
      item.innerHTML = `
        <div>
          <span class="animal-card-status"><span class="status-orb ${monitoringStatusClass(profile)}"></span>${monitoringStatusText(profile)}</span>
          <h2>${escapeHtml(name)}</h2>
          <p>${escapeHtml(sourceDisplayLabel(profile))} · ${escapeHtml(profileSpeciesLabel(profile))}</p>
        </div>
        <button type="button" class="btn btn-secondary">Open monitoring</button>
      `;
      item.querySelector('button').addEventListener('click', () => navigate(`#/animals/${encodeURIComponent(profile.animal_id)}`));
      list.appendChild(item);
    });
  }
  container.appendChild(list);
  return container;
}

function createAnimalsSection(animals, navigate, { includeAddAnimal = true } = {}) {
  const section = document.createElement('section');
  section.className = 'animals-section';
  if (!includeAddAnimal && animals.length === 1) {
    section.classList.add('animals-section--single-profile');
  }
  section.innerHTML = '<div class="animals-section-heading"><h2>My Animals</h2><p>Only configured profiles are shown here.</p></div>';
  const grid = document.createElement('div');
  grid.className = 'animal-card-grid';
  animals.forEach((animal) => grid.appendChild(createAnimalCard(animal, navigate)));
  if (includeAddAnimal) {
    grid.appendChild(createAddAnimalCard(navigate));
  }
  section.appendChild(grid);
  return section;
}

function createHero(profile, navigate) {
  const name = profile.animal_name || profile.animal_id;
  const species = profileSpeciesLabel(profile);
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
      <div class="animal-hero-status"><span class="status-orb ${monitoringStatusClass(profile)}"></span>${monitoringStatusText(profile)}</div>
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
      <span class="animal-card-status"><span class="status-orb ${monitoringStatusClass(profile)}"></span>${monitoringStatusText(profile)}</span>
      <h3>${escapeHtml(name)}</h3>
      <p>${escapeHtml(profileSpeciesLabel(profile))}</p>
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

function createAddAnimalCard(navigate) {
  const card = document.createElement('article');
  card.className = 'add-animal-card';
  card.tabIndex = 0;
  card.setAttribute('role', 'link');
  card.setAttribute('aria-label', 'Add an animal');
  card.innerHTML = `
    <span class="add-animal-icon" aria-hidden="true">+</span>
    <h3>Add Animal</h3>
    <p>Save an animal profile now and connect a monitoring source later.</p>
    <span class="add-animal-state">Start profile</span>
  `;
  const open = () => navigate('#/animals/new');
  card.addEventListener('click', open);
  card.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      open();
    }
  });
  return card;
}

function sourceLabel(profile) {
  return sourceDisplayLabel(profile);
}

function orderAnimalsForDisplay(animals) {
  return [...animals].sort((left, right) => {
    const priorityDifference = animalDisplayPriority(left) - animalDisplayPriority(right);
    if (priorityDifference) return priorityDifference;
    return animalDisplayName(left).localeCompare(animalDisplayName(right), undefined, { sensitivity: 'base' });
  });
}

function animalDisplayPriority(profile) {
  return monitoringDisplayPriority(profile);
}

function animalDisplayName(profile) {
  return String(profile && (profile.animal_name || profile.animal_id) || '');
}

function escapeHtml(value) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
