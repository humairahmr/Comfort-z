/**
 * Comfort-z Main Frontend Controller & Router
 */

import { api } from './api.js';
import { state } from './state.js';
import { renderAllAnimals, renderMonitoringPage, renderOverview } from './components/overview.js';
import { renderAddAnimalOnboarding } from './components/onboarding.js';
import { renderDashboard } from './components/dashboard.js';
import { loadCurrentEnvironment } from './components/environment-current.mjs';

const appRoot = document.getElementById('app-root');
const healthAgent = document.getElementById('health-agent');
const healthStore = document.getElementById('health-store');
const statusDot = document.getElementById('status-dot');
const mobileHealth = document.getElementById('mobile-health');

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
      if (healthAgent) healthAgent.textContent = `Google ADK · ${health.model || 'Gemini'}`;
      if (healthStore) healthStore.textContent = `${health.observation_store}`;
      if (mobileHealth) mobileHealth.textContent = `${health.agent}`;
      if (statusDot) statusDot.className = 'status-dot';
    }
  } catch (err) {
    if (healthAgent) healthAgent.textContent = 'Monitoring service unavailable';
    if (mobileHealth) mobileHealth.textContent = 'Offline';
    if (statusDot) statusDot.className = 'status-dot offline';
  }
}

function updateNavActive(hash) {
  const navItems = [...document.querySelectorAll('[data-nav-route]')];

  navItems.forEach((item) => {
    item.classList.remove('active');
    item.removeAttribute('aria-current');
  });

  let activeRoute = 'overview';
  if (hash === '#/animals' || hash === '#/animals/new') {
    activeRoute = 'animals';
  } else if (hash === '#/monitoring') {
    activeRoute = 'monitoring';
  } else if (hash.startsWith('#/animals/')) {
    activeRoute = 'monitoring';
  }
  navItems
    .filter((item) => item.dataset.navRoute === activeRoute)
    .forEach((item) => {
      item.classList.add('active');
      item.setAttribute('aria-current', 'page');
    });
}

async function handleRoute() {
  const hash = window.location.hash || '#/overview';
  updateNavActive(hash);

  appRoot.innerHTML = `
    <div class="state-box">
      <div class="state-icon">⏳</div>
      <h3>Loading Animal Monitoring Data</h3>
      <p>Communicating with Comfort-z FastAPI backend...</p>
    </div>
  `;

  try {
    if (hash === '#/animals/new') {
      loadAddAnimalRoute();
    } else if (hash === '#/monitoring') {
      await loadMonitoringRoute();
    } else if (hash.startsWith('#/animals/')) {
      const rawId = hash.replace('#/animals/', '').split('#')[0].trim();
      const animalId = decodeURIComponent(rawId);
      await loadDashboardRoute(animalId);
    } else if (hash === '#/animals') {
      await loadAllAnimalsRoute();
    } else {
      await loadOverviewRoute();
    }
  } catch (err) {
    renderError('Failed to load data from Comfort-z backend', err.message);
  }
}

function loadAddAnimalRoute() {
  appRoot.innerHTML = '';
  appRoot.appendChild(renderAddAnimalOnboarding(navigate));
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

async function loadAllAnimalsRoute() {
  try {
    const animals = await api.getAnimals();
    state.animals = animals;
    appRoot.innerHTML = '';
    appRoot.appendChild(renderAllAnimals(animals, navigate));
  } catch (err) {
    renderError('Unable to load monitored animals', err.message);
  }
}

async function loadMonitoringRoute() {
  try {
    const animals = await api.getAnimals();
    state.animals = animals;
    appRoot.innerHTML = '';
    appRoot.appendChild(renderMonitoringPage(animals, navigate));
  } catch (err) {
    renderError('Unable to load monitoring profiles', err.message);
  }
}

async function loadDashboardRoute(animalId) {
  try {
    const profile = await api.getProfile(animalId);
    if (!profile) {
      renderAnimalNotFound(animalId);
      return;
    }
    const [observations, reports, ownerUpdates, currentEnvironment] = await Promise.all([
      api.getObservations(animalId, 10).catch(() => []),
      api.getReports(animalId, 5).catch(() => []),
      api.getOwnerUpdates(animalId, 20).catch(() => []),
      loadCurrentEnvironment(profile, (request) => api.getCurrentEnvironment(request)),
    ]);

    state.selectedAnimalId = animalId;
    state.currentProfile = profile;
    state.currentObservations = observations;
    state.currentReports = reports;

    const renderWithOwnerUpdates = (nextOwnerUpdates) => {
      appRoot.innerHTML = '';
      appRoot.appendChild(
        renderDashboard(
          animalId,
          profile,
          observations,
          reports,
          nextOwnerUpdates,
          navigate,
          () => loadDashboardRoute(animalId),
          async (savedOwnerUpdateId = null) => {
            const refreshedUpdates = await api.getOwnerUpdates(animalId, 20);
            if (savedOwnerUpdateId && !refreshedUpdates.some((update) => update.owner_update_id === savedOwnerUpdateId)) {
              throw new Error('Update was saved, but Care updates could not be refreshed. Please use Refresh updates; do not submit it again.');
            }
            renderWithOwnerUpdates(refreshedUpdates);
          },
          currentEnvironment,
        )
      );
    };

    renderWithOwnerUpdates(ownerUpdates);
  } catch (err) {
    renderError(`Failed to load dashboard for animal: ${animalId}`, err.message);
  }
}

function renderAnimalNotFound(animalId) {
  appRoot.innerHTML = `
    <div class="state-box">
      <h3>Animal profile not found</h3>
      <p>No saved monitoring profile exists for ${escapeHtml(animalId)}.</p>
      <div style="margin-top: var(--space-4);"><button class="btn btn-secondary" onclick="window.location.hash='#/animals'">View All Animals</button></div>
    </div>
  `;
}

function renderError(title, detail) {
  appRoot.innerHTML = `
    <div class="state-box" style="border-color: var(--color-terracotta); background-color: var(--color-terracotta-light);">
      <div class="state-icon" style="color: var(--color-terracotta);">⚠️</div>
      <h3 style="color: var(--color-terracotta-dark);">${title}</h3>
      <p style="color: var(--color-terracotta-dark);">${detail || 'Check server connection and try again.'}</p>
      <div style="margin-top: var(--space-4);">
        <button class="btn btn-secondary" onclick="window.location.hash='#/overview'">Return to Overview</button>
      </div>
    </div>
  `;
}

function escapeHtml(value) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

// Global Brand Click
const brandBlock = document.getElementById('brand-home');
if (brandBlock) {
  brandBlock.addEventListener('click', (e) => {
    e.preventDefault();
    navigate('#/overview');
  });
}

// Initial Launch
syncHealth();
handleRoute();
