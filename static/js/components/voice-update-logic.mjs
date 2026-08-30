/** Deterministic eligibility and persistence rules for transient voice drafts. */

const CATEGORIES = new Set(['measurement', 'feeding', 'care', 'appetite', 'behavior', 'availability', 'note']);

export function evaluateVoiceAutoSave(response = {}) {
  const drafts = Array.isArray(response.drafts) ? response.drafts : [];
  if (!drafts.length) return { eligible: false, reason: 'No clear care updates were found.', payloads: [] };
  if (Array.isArray(response.review_warnings) && response.review_warnings.some(hasText)) {
    return { eligible: false, reason: 'This batch needs review.', payloads: [] };
  }

  const payloads = [];
  for (const draft of drafts) {
    const result = voiceDraftPayload(draft);
    if (result.error) return { eligible: false, reason: result.error, payloads: [] };
    payloads.push(result.payload);
  }
  return { eligible: true, reason: null, payloads };
}

export function voiceDraftPayload(draft = {}) {
  const category = String(draft.category || '').trim().toLowerCase();
  if (!CATEGORIES.has(category)) return { error: 'This update needs a valid category.' };
  if (!hasResolvedTimestamp(draft.occurred_at)) return { error: 'Choose when each voice update happened before saving.' };
  if (draft.unit_confirmation_required) {
    return { error: 'Choose Celsius or Fahrenheit before saving this temperature.' };
  }
  if (hasText(draft.review_warning)) return { error: 'This update needs review before saving.' };

  const payload = { category, occurred_at: new Date(draft.occurred_at).toISOString(), input_method: 'voice' };
  if (category !== 'measurement') {
    const note = String(draft.note || '').trim();
    if (!note || note.length > 500) return { error: 'Each care update needs a concise note.' };
    return { payload: { ...payload, note } };
  }

  const reading = draft.reading || {};
  const readingType = String(reading.reading_type || '').trim();
  const rawValue = reading.value;
  const value = Number(reading.value);
  const unit = String(reading.unit || '').trim();
  if (!readingType || readingType.length > 100 || rawValue === '' || rawValue == null || !Number.isFinite(value) || !unit || unit.length > 32) {
    return { error: 'Each measurement needs a type, numeric value, and unit.' };
  }
  if (/temperature/i.test(readingType) && !isCanonicalTemperatureUnit(unit)) {
    return { error: 'Choose Celsius or Fahrenheit before saving this temperature.' };
  }
  return { payload: { ...payload, reading: { reading_type: readingType, value, unit } } };
}

export async function persistVoiceAutoSaveBatch({ animalId, payloads, createOwnerUpdate }) {
  const saved = [];
  const pending = Array.isArray(payloads) ? payloads : [];

  for (let index = 0; index < pending.length; index += 1) {
    const payload = pending[index];
    try {
      const response = await createOwnerUpdate(animalId, payload);
      saved.push({ payload, ownerUpdateId: response?.owner_update_id || null });
    } catch (error) {
      return {
        complete: false,
        saved,
        unsaved: pending.slice(index),
        error,
      };
    }
  }
  return { complete: true, saved, unsaved: [], error: null };
}

export async function refreshSavedVoiceUpdates(saved, refreshOwnerUpdates) {
  if (!Array.isArray(saved) || !saved.length || typeof refreshOwnerUpdates !== 'function') return false;
  await refreshOwnerUpdates(saved.at(-1).ownerUpdateId);
  return true;
}

function hasResolvedTimestamp(value) {
  return Boolean(value) && Number.isFinite(Date.parse(value));
}

function hasText(value) {
  return Boolean(String(value || '').trim());
}

function isCanonicalTemperatureUnit(unit) {
  return ['C', 'F'].includes(String(unit || '').trim().replace(/^°+/, '').toUpperCase());
}
