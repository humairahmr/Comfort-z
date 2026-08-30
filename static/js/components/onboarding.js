/** Owner-facing profile creation with no monitoring-source configuration. */

import { api } from '../api.js';

export function renderAddAnimalOnboarding(navigate) {
  const container = document.createElement('div');
  container.className = 'onboarding-container';
  container.innerHTML = `
    <nav class="nav-breadcrumb" aria-label="Breadcrumb">
      <a href="#/animals" data-back-to-animals>All Animals</a>
      <span aria-hidden="true">/</span>
      <span aria-current="page">Add Animal</span>
    </nav>
    <header class="onboarding-heading">
      <h1>Add an animal</h1>
      <p>Start with the animal and care goal. A monitoring source can be connected later.</p>
    </header>
    <form class="onboarding-form" novalidate>
      <section class="onboarding-section" aria-labelledby="animal-details-heading">
        <h2 id="animal-details-heading">About your animal</h2>
        <div class="onboarding-field-grid">
          <label class="onboarding-field">
            <span>Animal name <em>Required</em></span>
            <input name="animalName" type="text" autocomplete="off" required maxlength="120" placeholder="For example, Raku">
          </label>
          <label class="onboarding-field">
            <span>Species <em>Optional</em></span>
            <input name="species" type="text" autocomplete="off" maxlength="160" placeholder="For example, Betta splendens">
            <small>If you know it. Comfort-z can help identify it later.</small>
          </label>
          <label class="onboarding-field">
            <span>Enclosure or environment <em>Optional</em></span>
            <input name="enclosureType" type="text" autocomplete="off" maxlength="120" placeholder="For example, aquarium">
          </label>
          <label class="onboarding-field">
            <span>Location label <em>Optional</em></span>
            <input name="locationName" type="text" autocomplete="off" maxlength="160" placeholder="For example, home office">
          </label>
        </div>
      </section>
      <section class="onboarding-section" aria-labelledby="care-goal-heading">
        <h2 id="care-goal-heading">What should Comfort-z watch for?</h2>
        <label class="onboarding-field onboarding-field-wide">
          <span>Monitoring goal <em>Required</em></span>
          <textarea name="monitoringGoal" rows="4" required maxlength="500" placeholder="Keep an eye on your animal."></textarea>
        </label>
      </section>
      <p class="onboarding-source-note">No source is connected yet. Saving this profile will not start monitoring or generate an observation.</p>
      <div class="onboarding-actions">
        <button type="button" class="btn btn-secondary" data-cancel>Add later</button>
        <button type="submit" class="btn btn-primary" data-submit>Save animal profile</button>
      </div>
      <p class="onboarding-message" role="status" aria-live="polite"></p>
    </form>
  `;

  const form = container.querySelector('form');
  const nameInput = form.elements.animalName;
  const goalInput = form.elements.monitoringGoal;
  const message = form.querySelector('.onboarding-message');
  const submitButton = form.querySelector('[data-submit]');
  let goalWasEdited = false;
  let generatedAnimalId = null;
  let isSubmitting = false;

  const suggestedGoal = () => {
    const name = nameInput.value.trim();
    return name ? `Keep an eye on ${name}.` : '';
  };

  nameInput.addEventListener('input', () => {
    generatedAnimalId = null;
    if (!goalWasEdited) goalInput.value = suggestedGoal();
  });
  goalInput.addEventListener('input', () => {
    goalWasEdited = true;
  });
  container.querySelector('[data-back-to-animals]').addEventListener('click', (event) => {
    event.preventDefault();
    navigate('#/animals');
  });
  form.querySelector('[data-cancel]').addEventListener('click', () => navigate('#/animals'));

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (isSubmitting) return;

    const animalName = nameInput.value.trim();
    const monitoringGoal = goalInput.value.trim();
    if (!animalName || !monitoringGoal) {
      message.textContent = 'Enter an animal name and monitoring goal before saving.';
      message.dataset.state = 'error';
      return;
    }

    generatedAnimalId ||= createAnimalId(animalName);
    const payload = {
      animal_id: generatedAnimalId,
      animal_name: animalName,
      monitoring_goal: monitoringGoal,
      timezone: browserTimezone(),
    };
    addOptionalValue(payload, 'expected_species', form.elements.species.value);
    addOptionalValue(payload, 'enclosure_type', form.elements.enclosureType.value);
    addOptionalValue(payload, 'location_name', form.elements.locationName.value);

    isSubmitting = true;
    submitButton.disabled = true;
    message.textContent = 'Saving animal profile…';
    message.dataset.state = 'pending';
    try {
      await api.createMonitoringProfile(payload);
      navigate('#/animals');
    } catch (error) {
      message.textContent = error.message || 'Unable to save this animal profile.';
      message.dataset.state = 'error';
      isSubmitting = false;
      submitButton.disabled = false;
    }
  });

  return container;
}

function addOptionalValue(payload, key, value) {
  const trimmed = value.trim();
  if (trimmed) payload[key] = trimmed;
}

function browserTimezone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch (_) {
    return 'UTC';
  }
}

function createAnimalId(name) {
  const slug = name
    .toLowerCase()
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '') || 'animal';
  const randomBytes = new Uint32Array(1);
  crypto.getRandomValues(randomBytes);
  return `${slug}-${randomBytes[0].toString(36).slice(0, 6)}`;
}
