/**
 * Comfort-z Main Frontend Controller & Router
 */

import { api } from './api.js';
import { state } from './state.js';
import { renderOverview } from './components/overview.js';
import { renderDashboard } from './components/dashboard.js';

const appRoot = document.getElementById('app-root');
const healthAgent = document.getElementById('health-agent');
const healthStore = document.getElementById('health-store');
const statusDot = document.getElementById('status-dot');

export function navigate(hash) {
  window.location.hash = hash;
}

window.addEventListener('hashchange', () => {
  handleRoute();
});

async function syncHealth() {
  try {
    const health = await api.getHealth();
    state.health = health;
    if (health) {
      if (healthAgent) healthAgent.textContent = `${health.agent} (${health.model})`;
      if (healthStore) healthStore.textContent = `${health.observation_store}`;
      if (statusDot) statusDot.className = 'status-dot';
    }
  } catch (err) {
    if (healthAgent) healthAgent.textContent = 'Offline / Connecting';
    if (statusDot) statusDot.className = 'status-dot offline';
  }
}

async function handleRoute() {
  const hash = window.location.hash || '#/overview';
  appRoot.innerHTML = `
    <div class="state-box">
      <div class="state-icon">⏳</div>
      <h3>Loading Animal Monitoring Data</h3>
      <p>Communicating with Comfort-z FastAPI backend...</p>
    </div>
  `;

  try {
    if (hash.startsWith('#/animals/')) {
      const rawId = hash.replace('#/animals/', '').trim();
      const animalId = decodeURIComponent(rawId);
      await loadDashboardRoute(animalId);
    } else {
      await loadOverviewRoute();
    }
  } catch (err) {
    renderError('Failed to load data from Comfort-z backend', err.message);
  }
}

async function loadOverviewRoute() {
  try {
    const animals = await api.getAnimals();
    state.animals = animals;
    appRoot.innerHTML = '';
    appRoot.appendChild(renderOverview(animals, navigate));
  } catch (err) {
    renderError('Unable to load monitored animals', err.message);
  }
}

async function loadDashboardRoute(animalId) {
  try {
    const [profile, observations, reports] = await Promise.all([
      api.getProfile(animalId).catch(() => null),
      api.getObservations(animalId, 10).catch(() => []),
      api.getReports(animalId, 5).catch(() => []),
    ]);

    state.selectedAnimalId = animalId;
    state.currentProfile = profile;
    state.currentObservations = observations;
    state.currentReports = reports;

    appRoot.innerHTML = '';
    appRoot.appendChild(
      renderDashboard(animalId, profile, observations, reports, navigate, () => loadDashboardRoute(animalId))
    );
  } catch (err) {
    renderError(`Failed to load dashboard for animal: ${animalId}`, err.message);
  }
}

function renderError(title, detail) {
  appRoot.innerHTML = `
    <div class="state-box" style="border-color: var(--color-coral); background-color: var(--color-coral-light);">
      <div class="state-icon" style="color: var(--color-coral);">⚠️</div>
      <h3 style="color: var(--color-coral-dark);">${title}</h3>
      <p style="color: var(--color-coral-dark);">${detail || 'Check server connection and try again.'}</p>
      <div style="margin-top: var(--space-4);">
        <button class="btn btn-secondary" onclick="window.location.hash='#/overview'">Return to Overview</button>
      </div>
    </div>
  `;
}

// Global Brand Click
const brandBlock = document.getElementById('brand-home');
if (brandBlock) {
  brandBlock.addEventListener('click', () => navigate('#/overview'));
}

// Initial Launch
syncHealth();
handleRoute();

