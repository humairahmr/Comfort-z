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
      const isFormData = typeof FormData !== 'undefined' && options.body instanceof FormData;
      const response = await fetch(url, {
        headers: {
          'Accept': 'application/json',
          ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
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
    const result = await this.fetchJson(`/animals/${encodeURIComponent(animalId)}/observations?limit=${limit}`);
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
   * Turn one temporary voice recording into review-only drafts. This never saves care updates.
   */
  async createVoiceUpdateDrafts(animalId, recording, metadata) {
    if (!animalId) throw new Error('Animal ID is required to add a voice update.');
    const form = new FormData();
    form.append('audio', recording, 'owner-update.webm');
    form.append('capture_timestamp', metadata.captureTimestamp);
    form.append('capture_duration_ms', String(metadata.captureDurationMs));
    if (metadata.browserTimezone) form.append('browser_timezone', metadata.browserTimezone);
    if (metadata.locale) form.append('locale', metadata.locale);
    return this.fetchJson(`/animals/${encodeURIComponent(animalId)}/owner-update-drafts/voice`, {
      method: 'POST',
      body: form,
    });
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

  async setMonitoringSource(animalId, source) {
    if (!animalId) throw new Error('Animal ID is required to connect a source.');
    return this.fetchJson(`/monitoring/${encodeURIComponent(animalId)}/source`, {
      method: 'PUT',
      body: JSON.stringify(source),
    });
  }

  async disconnectMonitoringSource(animalId) {
    if (!animalId) throw new Error('Animal ID is required to disconnect a source.');
    return this.fetchJson(`/monitoring/${encodeURIComponent(animalId)}/source`, { method: 'DELETE' });
  }

  async startMonitoring(animalId) {
    if (!animalId) throw new Error('Animal ID is required to start monitoring.');
    return this.fetchJson(`/monitoring/${encodeURIComponent(animalId)}/start`, { method: 'POST' });
  }

  async pauseMonitoring(animalId) {
    if (!animalId) throw new Error('Animal ID is required to pause monitoring.');
    return this.fetchJson(`/monitoring/${encodeURIComponent(animalId)}/pause`, { method: 'POST' });
  }

  async updateMonitoringLocation(animalId, location) {
    if (!animalId) throw new Error('Animal ID is required to update location.');
    return this.fetchJson(`/monitoring/${encodeURIComponent(animalId)}/location`, {
      method: 'PUT',
      body: JSON.stringify(location),
    });
  }

  async getCurrentEnvironment({ latitude, longitude, locationName = null }) {
    const parameters = new URLSearchParams({
      latitude: String(latitude),
      longitude: String(longitude),
    });
    if (locationName) parameters.set('location_name', locationName);
    return this.fetchJson(`/environment/current?${parameters.toString()}`);
  }

  async previewLocalCamera(cameraIndex) {
    if (!Number.isInteger(cameraIndex) || cameraIndex < 0) {
      throw new Error('Enter a whole camera index of 0 or higher.');
    }
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10_000);
    try {
      const response = await fetch(`${this.baseUrl}/monitoring/camera-preview`, {
        method: 'POST',
        headers: { 'Accept': 'image/jpeg', 'Content-Type': 'application/json' },
        body: JSON.stringify({ camera_index: cameraIndex }),
        signal: controller.signal,
      });
      if (!response.ok) {
        let detail = `HTTP ${response.status}`;
        try { detail = (await response.json()).detail || detail; } catch (_) { /* non-JSON failure */ }
        throw new Error(detail);
      }
      const contentType = response.headers.get('content-type') || '';
      if (!contentType.toLowerCase().startsWith('image/jpeg')) {
        throw new Error('Camera preview did not return a JPEG image.');
      }
      const blob = await response.blob();
      if (!blob || blob.size <= 4) throw new Error('Camera preview image was empty.');
      if (blob.type && !blob.type.toLowerCase().startsWith('image/jpeg')) {
        throw new Error('Camera preview image was not a JPEG.');
      }
      return blob;
    } catch (error) {
      if (error && error.name === 'AbortError') {
        throw new Error('Camera preview timed out. Check the camera and try again.');
      }
      throw error;
    } finally {
      clearTimeout(timeout);
    }
  }

  async uploadProfilePhoto(animalId, photo) {
    if (!animalId) throw new Error('Animal ID is required to upload a profile photo.');
    if (!photo || (typeof File !== 'undefined' && !(photo instanceof File))) {
      throw new Error('Choose an image file first.');
    }
    return this.fetchForm(`/animals/${encodeURIComponent(animalId)}/profile-photo`, 'photo', photo);
  }

  async uploadMonitoringVideo(animalId, video) {
    if (!animalId) throw new Error('Animal ID is required to upload a monitoring video.');
    if (!video || (typeof File !== 'undefined' && !(video instanceof File))) {
      throw new Error('Choose a video file first.');
    }
    return this.fetchForm(`/monitoring/${encodeURIComponent(animalId)}/video-source`, 'video', video);
  }

  async fetchForm(endpoint, fieldName, file) {
    const form = new FormData();
    form.append(fieldName, file, file.name);
    return this.fetchJson(endpoint, { method: 'POST', body: form });
  }
}

export const api = new ApiClient();
