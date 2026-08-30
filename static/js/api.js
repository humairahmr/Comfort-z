/**
 * Comfort-z API Client
 * Connects the frontend to the existing FastAPI backend.
 */

export class ApiClient {
  constructor(baseUrl = '') {
    this.baseUrl = baseUrl;
  }

  async fetchJson(endpoint, options = {}) {
    const url = `${this.baseUrl}${endpoint}`;
    try {
      const response = await fetch(url, {
        headers: {
          'Accept': 'application/json',
          'Content-Type': 'application/json',
          ...options.headers,
        },
        ...options,
      });

      if (!response.ok) {
        if (response.status === 404) {
          return null;
        }
        let errorDetail = `HTTP ${response.status}`;
        try {
          const body = await response.json();
          if (body && body.detail) {
            errorDetail = body.detail;
          }
        } catch (_) {
          // ignore non-json error responses
        }
        throw new Error(errorDetail);
      }

      return await response.json();
    } catch (err) {
      console.warn(`API Error [${endpoint}]:`, err.message);
      throw err;
    }
  }

  /**
   * Health status of Cloud Run, ADK agent, and persistence store.
   */
  async getHealth() {
    return this.fetchJson('/health');
  }

  /**
   * Retrieve all saved monitoring profiles.
   */
  async getAnimals() {
    const result = await this.fetchJson('/animals');
    return Array.isArray(result) ? result : [];
  }

  /**
   * Save an animal's monitoring profile without starting a monitoring window.
   */
  async createMonitoringProfile(profile) {
    return this.fetchJson('/monitoring/profiles', {
      method: 'POST',
      body: JSON.stringify(profile),
    });
  }

  /**
   * Retrieve one animal's saved monitoring profile.
   */
  async getProfile(animalId) {
    if (!animalId) return null;
    return this.fetchJson(`/monitoring/${encodeURIComponent(animalId)}/profile`);
  }

  /**
   * Retrieve recent observation records for an animal (newest first).
   */
  async getObservations(animalId, limit = 10) {
    if (!animalId) return [];
    let result = await this.fetchJson(`/animals/${encodeURIComponent(animalId)}/observations?limit=${limit}`);
    if ((!result || result.length === 0) && animalId.toLowerCase() === 'raku') {
      const altId = animalId === 'raku' ? 'Raku' : 'raku';
      const altResult = await this.fetchJson(`/animals/${encodeURIComponent(altId)}/observations?limit=${limit}`);
      if (altResult && altResult.length > 0) {
        result = altResult;
      }
    }
    return Array.isArray(result) ? result : [];
  }

  /**
   * Retrieve persisted daily reports for an animal.
   */
  async getReports(animalId, limit = 5) {
    if (!animalId) return [];
    const result = await this.fetchJson(`/animals/${encodeURIComponent(animalId)}/reports?limit=${limit}`);
    return Array.isArray(result) ? result : [];
  }

  /**
   * Retrieve owner-provided care context separately from Gemini observations.
   */
  async getOwnerUpdates(animalId, limit = 20) {
    if (!animalId) return [];
    const result = await this.fetchJson(`/animals/${encodeURIComponent(animalId)}/owner-updates?limit=${limit}`);
    return Array.isArray(result) ? result : [];
  }

  /**
   * Save one owner update without starting monitoring or report generation.
   */
  async createOwnerUpdate(animalId, update) {
    if (!animalId) throw new Error('Animal ID is required to add an update.');
    const result = await this.fetchJson(`/animals/${encodeURIComponent(animalId)}/owner-updates`, {
      method: 'POST',
      body: JSON.stringify(update),
    });
    if (!result) throw new Error('Animal profile was not found.');
    if (typeof result.owner_update_id !== 'string' || !result.owner_update_id) {
      const error = new Error('The update may have been saved, but the server response could not confirm it. Refresh Care updates before trying again.');
      error.mayHavePersisted = true;
      throw error;
    }
    return result;
  }

  /**
   * Trigger a single bounded observation cycle for an animal.
   */
  async runNextWindow(animalId, windowMaxSamples = 1) {
    if (!animalId) throw new Error('Animal ID is required to run observation.');
    return this.fetchJson(`/monitoring/${encodeURIComponent(animalId)}/next-window`, {
      method: 'POST',
      body: JSON.stringify({ window_max_samples: windowMaxSamples }),
    });
  }

  /**
   * Synthesize a structured daily monitoring report from persisted observation history.
   */
  async generateDailyReport(animalId) {
    if (!animalId) throw new Error('Animal ID is required to generate a daily report.');
    return this.fetchJson(`/monitoring/${encodeURIComponent(animalId)}/daily-report`, {
      method: 'POST',
    });
  }
}

export const api = new ApiClient();
