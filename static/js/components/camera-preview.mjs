/** State-driven, side-effect-free rendering for local camera snapshots. */

const rememberedPreviews = new Map();

function initialState(animalId) {
  const remembered = rememberedPreviews.get(animalId);
  return remembered
    ? { status: 'success', url: remembered.url, pendingUrl: null, previousUrl: null, error: '' }
    : { status: 'idle', url: null, pendingUrl: null, previousUrl: null, error: '' };
}

/**
 * Owns preview state independently from a particular dashboard DOM subtree.
 * A dashboard rerender can therefore render the same completed blob URL without
 * relying on handlers attached to an earlier <img> element.
 */
export function createCameraPreviewState({
  animalId,
  render,
  createObjectUrl = (blob) => URL.createObjectURL(blob),
  revokeObjectUrl = (url) => URL.revokeObjectURL(url),
}) {
  let state = initialState(animalId);
  let pending = null;
  let imageTimeout = null;

  const clearImageTimeout = () => {
    if (imageTimeout !== null) clearTimeout(imageTimeout);
    imageTimeout = null;
  };

  const publish = () => {
    if (state.url) rememberedPreviews.set(animalId, { url: state.url });
    else rememberedPreviews.delete(animalId);
    render({ ...state });
  };

  const settleImageFailure = (url, error) => {
    if (!pending || state.pendingUrl !== url) return;
    const previousUrl = state.previousUrl;
    const rejected = pending;
    pending = null;
    clearImageTimeout();
    revokeObjectUrl(url);
    state = previousUrl
      ? { status: 'success', url: previousUrl, pendingUrl: null, previousUrl: null, error: '' }
      : { status: 'error', url: null, pendingUrl: null, previousUrl: null, error: error.message };
    publish();
    rejected.reject(error);
  };

  return {
    get state() { return { ...state }; },
    render() { publish(); },
    start() {
      state = { ...state, status: 'loading', pendingUrl: null, previousUrl: null, error: '' };
      publish();
    },
    show(blob) {
      return new Promise((resolve, reject) => {
        const nextUrl = createObjectUrl(blob);
        pending = { url: nextUrl, resolve, reject };
        state = {
          status: 'loading',
          url: nextUrl,
          pendingUrl: nextUrl,
          previousUrl: state.url,
          error: '',
        };
        imageTimeout = setTimeout(
          () => settleImageFailure(nextUrl, new Error('Camera preview image could not be displayed.')),
          8_000,
        );
        publish();
      });
    },
    imageLoaded(url) {
      if (!pending || state.pendingUrl !== url) return;
      const previousUrl = state.previousUrl;
      const resolved = pending;
      pending = null;
      clearImageTimeout();
      state = { status: 'success', url, pendingUrl: null, previousUrl: null, error: '' };
      publish();
      if (previousUrl && previousUrl !== url) revokeObjectUrl(previousUrl);
      resolved.resolve();
    },
    imageFailed(url, error = new Error('Camera preview image could not be displayed.')) {
      settleImageFailure(url, error);
    },
    fail(error) {
      if (state.pendingUrl) {
        settleImageFailure(state.pendingUrl, error);
        return;
      }
      if (state.status !== 'loading') return;
      state = state.url
        ? { ...state, status: 'success', error: '' }
        : { status: 'error', error: error.message || 'Unable to capture a camera snapshot.' };
      publish();
    },
  };
}

export function createCameraPreviewController({ requestPreview, previewState, setMessage }) {
  let inFlight = false;

  return {
    get inFlight() { return inFlight; },
    async capture(cameraIndex) {
      if (inFlight) return false;
      inFlight = true;
      previewState.start();
      setMessage('Capturing camera snapshot…');
      try {
        const blob = await requestPreview(cameraIndex);
        await previewState.show(blob);
        setMessage('');
        return true;
      } catch (error) {
        previewState.fail(error);
        setMessage(error && error.message ? error.message : 'Unable to capture a camera snapshot.');
        return false;
      } finally {
        inFlight = false;
      }
    },
  };
}

export function clearRememberedCameraPreview(animalId) {
  const current = rememberedPreviews.get(animalId);
  if (current) URL.revokeObjectURL(current.url);
  rememberedPreviews.delete(animalId);
}
