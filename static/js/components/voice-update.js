/**
 * Short, owner-controlled microphone capture for care-update drafts.
 * Audio stays in memory until it is sent once to the backend and is never persisted here.
 */

import { api } from '../api.js';
import { formatDirectReadingValue, formatReadingType } from './environment-readings.mjs';
import { evaluateVoiceAutoSave, persistVoiceAutoSaveBatch, refreshSavedVoiceUpdates } from './voice-update-logic.mjs';

const MAX_RECORDING_MS = 60_000;
const CATEGORIES = ['measurement', 'feeding', 'care', 'appetite', 'behavior', 'availability', 'note'];

export function createVoiceUpdatePanel(animalId, onOwnerUpdatesRefresh) {
  const panel = document.createElement('section');
  panel.className = 'voice-update-panel';
  panel.hidden = true;
  panel.setAttribute('aria-label', 'Voice care update');

  const status = document.createElement('p');
  status.className = 'voice-update-status';
  status.setAttribute('role', 'status');
  status.setAttribute('aria-live', 'polite');

  const recordingControls = document.createElement('div');
  recordingControls.className = 'voice-recording-controls';
  const timer = document.createElement('span');
  timer.className = 'voice-update-timer';
  timer.textContent = '0:00';
  const stop = button('Stop', 'btn btn-primary');
  const cancel = button('Cancel', 'btn btn-secondary');
  recordingControls.append(timer, stop, cancel);

  const transcriptSection = document.createElement('div');
  transcriptSection.className = 'voice-update-transcript';
  transcriptSection.hidden = true;
  const transcriptLabel = document.createElement('strong');
  transcriptLabel.textContent = 'Heard';
  const transcript = document.createElement('textarea');
  transcript.readOnly = true;
  transcript.rows = 3;
  transcript.setAttribute('aria-label', 'Voice update transcript');
  const copyTranscript = button('Copy transcript', 'btn btn-secondary');
  transcriptSection.append(transcriptLabel, transcript, copyTranscript);

  const draftsSection = document.createElement('div');
  draftsSection.className = 'voice-update-drafts';
  draftsSection.hidden = true;
  const draftsHeading = document.createElement('strong');
  draftsHeading.textContent = 'Comfort-z understood';
  const draftsList = document.createElement('div');
  draftsList.className = 'voice-update-draft-list';
  const reviewWarning = document.createElement('p');
  reviewWarning.className = 'voice-update-review-warning';
  const save = button('Save updates', 'btn btn-primary');
  const discard = button('Discard', 'btn btn-secondary');
  const refresh = button('Refresh updates', 'btn btn-secondary');
  refresh.hidden = true;
  const draftActions = document.createElement('div');
  draftActions.className = 'voice-update-actions';
  draftActions.append(discard, refresh, save);
  draftsSection.append(draftsHeading, draftsList, reviewWarning, draftActions);

  const autoSaveSection = document.createElement('div');
  autoSaveSection.className = 'voice-update-autosave';
  autoSaveSection.hidden = true;
  const autoSaveHeading = document.createElement('strong');
  autoSaveHeading.textContent = 'Saved';
  const autoSaveSummary = document.createElement('div');
  autoSaveSummary.className = 'voice-update-autosave-summary';
  const viewTranscript = button('View transcript', 'voice-update-transcript-toggle');
  const autoSaveTranscript = document.createElement('p');
  autoSaveTranscript.className = 'voice-update-autosave-transcript';
  autoSaveTranscript.hidden = true;
  const autoRefresh = button('Refresh care updates', 'btn btn-secondary');
  autoRefresh.hidden = true;
  autoSaveSection.append(autoSaveHeading, autoSaveSummary, viewTranscript, autoSaveTranscript, autoRefresh);

  panel.append(status, recordingControls, transcriptSection, draftsSection, autoSaveSection);

  let stream = null;
  let recorder = null;
  let chunks = [];
  let recordingStartedAt = 0;
  let captureTimestamp = null;
  let timerInterval = null;
  let autoStopTimeout = null;
  let cancelled = false;
  let drafts = [];
  let saving = false;
  let lastSavedOwnerUpdateId = null;
  let recordingGeneration = 0;
  let autoSaveRefreshPending = false;
  let autoRefreshTimeout = null;
  let autoSavedUpdates = [];

  const setStatus = (message, state = '') => {
    status.textContent = message;
    status.dataset.state = state;
  };

  const closeAudio = () => {
    clearInterval(timerInterval);
    clearTimeout(autoStopTimeout);
    timerInterval = null;
    autoStopTimeout = null;
    if (stream) stream.getTracks().forEach((track) => track.stop());
    stream = null;
  };

  const reset = ({ hide = false } = {}) => {
    recordingGeneration += 1;
    closeAudio();
    clearTimeout(autoRefreshTimeout);
    autoRefreshTimeout = null;
    recorder = null;
    chunks = [];
    drafts = [];
    saving = false;
    lastSavedOwnerUpdateId = null;
    cancelled = false;
    transcript.value = '';
    transcriptSection.hidden = true;
    draftsSection.hidden = true;
    autoSaveSection.hidden = true;
    autoSaveTranscript.hidden = true;
    autoSaveSummary.replaceChildren();
    viewTranscript.textContent = 'View transcript';
    autoSavedUpdates = [];
    recordingControls.hidden = true;
    refresh.hidden = true;
    autoRefresh.hidden = true;
    save.disabled = false;
    reviewWarning.textContent = '';
    setStatus('');
    if (hide) panel.hidden = true;
  };

  const updateTimer = () => {
    const elapsed = Math.min(MAX_RECORDING_MS, Date.now() - recordingStartedAt);
    timer.textContent = formatDuration(elapsed);
  };

  const renderDrafts = () => {
    draftsList.replaceChildren();
    drafts.forEach((draft, index) => {
      draftsList.appendChild(createDraftEditor(draft, index, () => {
        drafts.splice(index, 1);
        renderDrafts();
      }));
    });
    save.disabled = drafts.length === 0 || saving;
    save.textContent = drafts.length === 1 ? 'Save update' : `Save ${drafts.length} updates`;
  };

  const showReview = (result, { draftOverrides = null, message = null } = {}) => {
    transcript.value = result.transcript || '';
    transcriptSection.hidden = false;
    drafts = Array.isArray(draftOverrides) ? draftOverrides.map((draft) => ({ ...draft }))
      : Array.isArray(result.drafts) ? result.drafts.map((draft) => ({ ...draft })) : [];
    draftsSection.hidden = false;
    autoSaveSection.hidden = true;
    recordingControls.hidden = true;
    reviewWarning.textContent = message || (Array.isArray(result.review_warnings) && result.review_warnings.length
      ? result.review_warnings.join(' ')
      : drafts.length ? 'Review each update before saving. Nothing has been saved yet.' : 'No clear care updates were found. You can copy the transcript and add a typed update instead.');
    renderDrafts();
  };

  const renderAutoSaveSummary = (saved) => {
    autoSaveSummary.replaceChildren();
    saved.forEach(({ payload }) => {
      const item = document.createElement('p');
      item.className = 'voice-update-autosave-item';
      item.textContent = voicePayloadSummary(payload);
      autoSaveSummary.appendChild(item);
    });
  };

  const refreshAutoSavedUpdates = async () => {
    if (autoSaveRefreshPending || typeof onOwnerUpdatesRefresh !== 'function') return;
    autoSaveRefreshPending = true;
    try {
      await refreshSavedVoiceUpdates(autoSavedUpdates, onOwnerUpdatesRefresh);
    } catch (error) {
      autoRefresh.hidden = false;
      setStatus(error.message || 'Updates were saved, but Care updates could not refresh.', 'error');
    } finally {
      autoSaveRefreshPending = false;
    }
  };

  const showAutoSaveSuccess = (result, outcome) => {
    transcript.value = result.transcript || '';
    autoSaveTranscript.textContent = result.transcript || '';
    autoSaveTranscript.hidden = true;
    viewTranscript.hidden = !autoSaveTranscript.textContent;
    autoSaveHeading.textContent = outcome.saved.length === 1 ? 'Saved' : `Saved ${outcome.saved.length} updates`;
    renderAutoSaveSummary(outcome.saved);
    transcriptSection.hidden = true;
    draftsSection.hidden = true;
    autoSaveSection.hidden = false;
    setStatus(outcome.saved.length === 1 ? 'Update saved. Refreshing Care updatesâ€¦' : `${outcome.saved.length} updates saved. Refreshing Care updatesâ€¦`, 'success');

    // Keep the compact confirmation visible briefly before the dashboard refreshes.
    clearTimeout(autoRefreshTimeout);
    autoRefreshTimeout = window.setTimeout(() => { refreshAutoSavedUpdates(); }, 750);
  };

  const processRecording = async () => {
    const duration = Math.max(1, Date.now() - recordingStartedAt);
    const mimeType = recorder && recorder.mimeType ? recorder.mimeType : 'audio/webm';
    const audio = new Blob(chunks, { type: mimeType });
    chunks = [];
    closeAudio();
    recordingControls.hidden = true;
    if (cancelled || audio.size === 0) {
      if (!cancelled) setStatus('No audio was captured. You can add an update manually.', 'error');
      return;
    }
    setStatus('Transcribing and preparing drafts…', 'pending');
    try {
      const result = await api.createVoiceUpdateDrafts(animalId, audio, {
        captureTimestamp,
        captureDurationMs: duration,
        browserTimezone: Intl.DateTimeFormat().resolvedOptions().timeZone || '',
        locale: navigator.language || '',
      });
      const safeResult = result || {};
      const eligibility = evaluateVoiceAutoSave(safeResult);
      if (!eligibility.eligible) {
        showReview(safeResult);
        if (Array.isArray(safeResult.drafts) && safeResult.drafts.length) {
          setStatus('Review the suggested updates before saving.', 'success');
        } else {
          setStatus('No drafts were prepared. Nothing was saved; you can copy the transcript into a typed update.', 'error');
        }
        return;
      }

      saving = true;
      setStatus('Saving clear care updateâ€¦', 'pending');
      const outcome = await persistVoiceAutoSaveBatch({
        animalId,
        payloads: eligibility.payloads,
        createOwnerUpdate: (id, payload) => api.createOwnerUpdate(id, payload),
      });
      saving = false;
      lastSavedOwnerUpdateId = outcome.saved.at(-1)?.ownerUpdateId || null;
      if (outcome.complete) {
        autoSavedUpdates = outcome.saved;
        showAutoSaveSuccess(safeResult, outcome);
      } else {
        showReview(safeResult, {
          draftOverrides: outcome.unsaved,
          message: `${outcome.saved.length} update${outcome.saved.length === 1 ? '' : 's'} saved. Review and retry the remaining draft${outcome.unsaved.length === 1 ? '' : 's'}.`,
        });
        setStatus(outcome.error?.message || 'Some updates could not be saved. Unsaved drafts remain below.', 'error');
      }
    } catch (error) {
      setStatus(error.message || 'Voice update processing failed. Nothing was saved.', 'error');
      transcriptSection.hidden = false;
      transcript.value = '';
    }
  };

  const stopRecording = () => {
    if (!recorder || recorder.state === 'inactive') return;
    clearTimeout(autoStopTimeout);
    recorder.stop();
  };

  const start = async () => {
    reset();
    panel.hidden = false;
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      setStatus('Voice updates are unavailable in this browser. You can add an update manually.', 'error');
      return;
    }
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = supportedMimeType();
      recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
      const generation = recordingGeneration;
      recorder.addEventListener('dataavailable', (event) => {
        if (event.data && event.data.size > 0) chunks.push(event.data);
      });
      recorder.addEventListener('error', () => {
        cancelled = true;
        recordingGeneration += 1;
        closeAudio();
        setStatus('Recording stopped unexpectedly. Nothing was saved.', 'error');
      });
      recorder.addEventListener('stop', () => {
        if (generation === recordingGeneration) processRecording();
      }, { once: true });
      cancelled = false;
      captureTimestamp = new Date().toISOString();
      recordingStartedAt = Date.now();
      timer.textContent = '0:00';
      recordingControls.hidden = false;
      setStatus('Listening… Speak a short care update, then choose Stop.', 'recording');
      recorder.start();
      timerInterval = window.setInterval(updateTimer, 250);
      autoStopTimeout = window.setTimeout(stopRecording, MAX_RECORDING_MS);
    } catch (error) {
      closeAudio();
      const denied = error && error.name === 'NotAllowedError';
      setStatus(
        denied ? 'Microphone permission was not granted. You can add an update manually.' : 'Microphone recording could not start. You can add an update manually.',
        'error'
      );
    }
  };

  stop.addEventListener('click', stopRecording);
  cancel.addEventListener('click', () => {
    cancelled = true;
    if (recorder && recorder.state !== 'inactive') recorder.stop();
    reset({ hide: true });
  });
  discard.addEventListener('click', () => reset({ hide: true }));
  copyTranscript.addEventListener('click', async () => {
    if (!transcript.value) return;
    try {
      await navigator.clipboard.writeText(transcript.value);
      setStatus('Transcript copied. You can use it in a typed update.', 'success');
    } catch (_) {
      transcript.focus();
      transcript.select();
      setStatus('Select and copy the transcript to use it in a typed update.', 'pending');
    }
  });
  viewTranscript.addEventListener('click', () => {
    const opening = autoSaveTranscript.hidden;
    autoSaveTranscript.hidden = !opening;
    viewTranscript.textContent = opening ? 'Hide transcript' : 'View transcript';
  });
  autoRefresh.addEventListener('click', refreshAutoSavedUpdates);
  save.addEventListener('click', async () => {
    if (saving || !drafts.length) return;
    const parsed = [...draftsList.children].map(readDraft);
    const invalid = parsed.find((result) => result.error);
    if (invalid) {
      setStatus(invalid.error, 'error');
      return;
    }
    saving = true;
    renderDrafts();
    setStatus('Saving confirmed updates…', 'pending');
    const outcome = await persistVoiceAutoSaveBatch({
      animalId,
      payloads: parsed.map((result) => ({ ...result.payload, input_method: 'voice' })),
      createOwnerUpdate: (id, payload) => api.createOwnerUpdate(id, payload),
    });
    lastSavedOwnerUpdateId = outcome.saved.at(-1)?.ownerUpdateId || null;
    drafts = outcome.unsaved;
    saving = false;
    renderDrafts();
    if (!outcome.complete) {
      if (outcome.saved.length) setStatus(`${outcome.saved.length} update${outcome.saved.length === 1 ? '' : 's'} saved. Review and retry the remaining draft${outcome.unsaved.length === 1 ? '' : 's'}.`, 'error');
      else setStatus(outcome.error?.message || 'Some updates could not be saved. Unsaved drafts remain below.', 'error');
      return;
    }
    try {
      if (typeof onOwnerUpdatesRefresh === 'function') await onOwnerUpdatesRefresh(lastSavedOwnerUpdateId);
      reset({ hide: true });
    } catch (error) {
      refresh.hidden = false;
      setStatus(error.message || 'Updates were saved, but Care updates could not refresh.', 'error');
    }
  });
  refresh.addEventListener('click', async () => {
    try {
      if (typeof onOwnerUpdatesRefresh === 'function') await onOwnerUpdatesRefresh(lastSavedOwnerUpdateId);
      reset({ hide: true });
    } catch (error) {
      setStatus(error.message || 'Care updates could not refresh.', 'error');
    }
  });

  return { element: panel, open: start, close: () => reset({ hide: true }) };
}

function voicePayloadSummary(payload) {
  if (payload?.category === 'measurement' && payload.reading) {
    return `${formatReadingType(payload.reading.reading_type)} Â· ${formatDirectReadingValue(payload.reading)}`;
  }
  const label = String(payload?.category || 'Update').replace(/^./, (letter) => letter.toUpperCase());
  return `${label} Â· ${payload?.note || 'Owner-provided update.'}`;
}

function createDraftEditor(draft, index, onRemove) {
  const card = document.createElement('article');
  card.className = 'voice-update-draft';
  card.dataset.draftIndex = String(index);
  card.dataset.unitConfirmationRequired = String(Boolean(draft.unit_confirmation_required));
  const top = document.createElement('div');
  top.className = 'voice-update-draft-top';
  const title = document.createElement('strong');
  title.textContent = `Update ${index + 1}`;
  const remove = button('Remove', 'voice-update-remove');
  remove.addEventListener('click', onRemove);
  top.append(title, remove);

  const category = select('Category', 'category', CATEGORIES, draft.category || 'note');
  const occurredAt = input('When it happened', 'occurred_at', 'datetime-local', toLocalDateTime(draft.occurred_at));
  const warning = document.createElement('p');
  warning.className = 'voice-update-draft-warning';
  warning.textContent = draft.review_warning || '';
  const note = textarea('Update', 'note', draft.note || '');
  const reading = document.createElement('div');
  reading.className = 'voice-update-reading-fields';
  reading.append(
    input('Reading type', 'reading_type', 'text', draft.reading?.reading_type || ''),
    input('Value', 'reading_value', 'number', draft.reading?.value ?? ''),
    input('Unit', 'reading_unit', 'text', draft.reading?.unit || '')
  );
  const fields = document.createElement('div');
  fields.className = 'voice-update-draft-fields';
  fields.append(category, occurredAt, warning, note, reading);
  card.append(top, fields);

  const sync = () => {
    const measurement = category.querySelector('select').value === 'measurement';
    note.hidden = measurement;
    reading.hidden = !measurement;
  };
  category.querySelector('select').addEventListener('change', sync);
  sync();
  return card;
}

function readDraft(card) {
  const field = (name) => card.querySelector(`[name="${name}"]`);
  const category = field('category').value;
  const occurredAt = field('occurred_at').value;
  if (!occurredAt) return { error: 'Choose when each voice update happened before saving.' };
  const payload = { category, occurred_at: new Date(occurredAt).toISOString() };
  if (category === 'measurement') {
    const readingType = field('reading_type').value.trim();
    const valueText = field('reading_value').value.trim();
    const unit = field('reading_unit').value.trim();
    const value = Number(valueText);
    if (!readingType || !valueText || !Number.isFinite(value) || !unit) {
      return { error: 'Each measurement needs a type, numeric value, and unit.' };
    }
    if (card.dataset.unitConfirmationRequired === 'true' && isAmbiguousTemperatureUnit(readingType, unit)) {
      return { error: 'Choose Celsius or Fahrenheit before saving this temperature.' };
    }
    payload.reading = { reading_type: readingType, value, unit };
  } else {
    const note = field('note').value.trim();
    if (!note) return { error: 'Each care update needs a concise note.' };
    payload.note = note;
  }
  return { draft: { ...payload }, payload };
}

function isAmbiguousTemperatureUnit(readingType, unit) {
  if (!/temperature/i.test(readingType)) return false;
  const degree = String.fromCharCode(176);
  return ['', 'degree', 'degrees'].includes(
    unit.toLowerCase().split(degree).join('').trim().replace(/\s+/g, ' ')
  );
}

function button(label, className) {
  const element = document.createElement('button');
  element.type = 'button';
  element.className = className;
  element.textContent = label;
  return element;
}

function select(label, name, values, selected) {
  const wrapper = document.createElement('label');
  wrapper.className = 'voice-update-field';
  const caption = document.createElement('span');
  caption.textContent = label;
  const element = document.createElement('select');
  element.name = name;
  values.forEach((value) => {
    const option = document.createElement('option');
    option.value = value;
    option.textContent = value === 'behavior' ? 'Behaviour note' : value.replace(/^./, (letter) => letter.toUpperCase());
    option.selected = value === selected;
    element.appendChild(option);
  });
  wrapper.append(caption, element);
  return wrapper;
}

function input(label, name, type, value) {
  const wrapper = document.createElement('label');
  wrapper.className = 'voice-update-field';
  const caption = document.createElement('span');
  caption.textContent = label;
  const element = document.createElement('input');
  element.name = name;
  element.type = type;
  element.value = String(value ?? '');
  if (type === 'number') element.step = 'any';
  wrapper.append(caption, element);
  return wrapper;
}

function textarea(label, name, value) {
  const wrapper = document.createElement('label');
  wrapper.className = 'voice-update-field';
  const caption = document.createElement('span');
  caption.textContent = label;
  const element = document.createElement('textarea');
  element.name = name;
  element.maxLength = 500;
  element.value = value;
  wrapper.append(caption, element);
  return wrapper;
}

function supportedMimeType() {
  return ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/mp4']
    .find((mimeType) => MediaRecorder.isTypeSupported(mimeType));
}

function toLocalDateTime(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}

function formatDuration(milliseconds) {
  const totalSeconds = Math.floor(milliseconds / 1000);
  return `${Math.floor(totalSeconds / 60)}:${String(totalSeconds % 60).padStart(2, '0')}`;
}
