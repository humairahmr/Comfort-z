import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import {
  createCameraPreviewController,
  createCameraPreviewState,
} from './camera-preview.mjs';

async function flush() {
  await Promise.resolve();
  await Promise.resolve();
}

function createPreviewHarness(animalId) {
  const renders = [];
  const revoked = [];
  let sequence = 0;
  const previewState = createCameraPreviewState({
    animalId,
    render: (state) => renders.push({
      ...state,
      imageVisible: Boolean(state.url),
      spinnerVisible: state.status === 'loading',
    }),
    createObjectUrl: () => `blob:${animalId}-${++sequence}`,
    revokeObjectUrl: (url) => revoked.push(url),
  });
  return { previewState, renders, revoked };
}

test('a successful camera preview becomes visible only after its image load event', async () => {
  const { previewState, renders } = createPreviewHarness('preview-success');
  const messages = [];
  const controller = createCameraPreviewController({
    requestPreview: async (index) => ({ type: 'image/jpeg', size: 20, index }),
    previewState,
    setMessage: (message) => messages.push(message),
  });

  const capture = controller.capture(1);
  await flush();
  assert.equal(previewState.state.status, 'loading');
  assert.equal(previewState.state.url, 'blob:preview-success-1');
  assert.equal(renders.at(-1).spinnerVisible, true);

  previewState.imageLoaded('blob:preview-success-1');
  assert.equal(await capture, true);
  assert.equal(previewState.state.status, 'success');
  assert.equal(renders.at(-1).imageVisible, true);
  assert.equal(renders.at(-1).spinnerVisible, false);
  assert.equal(messages.at(-1), '');
});

test('a request failure clears loading and surfaces the capture error', async () => {
  const { previewState, renders } = createPreviewHarness('preview-request-error');
  const messages = [];
  const controller = createCameraPreviewController({
    requestPreview: async () => { throw new Error('Camera preview timed out. Check the camera and try again.'); },
    previewState,
    setMessage: (message) => messages.push(message),
  });

  assert.equal(await controller.capture(1), false);
  assert.equal(previewState.state.status, 'error');
  assert.equal(renders.at(-1).spinnerVisible, false);
  assert.equal(messages.at(-1), 'Camera preview timed out. Check the camera and try again.');
});

test('an image error clears loading and returns the preview to an error state', async () => {
  const { previewState, renders } = createPreviewHarness('preview-image-error');
  const messages = [];
  const controller = createCameraPreviewController({
    requestPreview: async () => ({ type: 'image/jpeg', size: 20 }),
    previewState,
    setMessage: (message) => messages.push(message),
  });

  const capture = controller.capture(1);
  await flush();
  previewState.imageFailed('blob:preview-image-error-1');

  assert.equal(await capture, false);
  assert.equal(previewState.state.status, 'error');
  assert.equal(renders.at(-1).spinnerVisible, false);
  assert.match(messages.at(-1), /could not be displayed/i);
});

test('duplicate preview clicks while a request is active issue only one capture request', async () => {
  const { previewState } = createPreviewHarness('preview-single-flight');
  let requestCount = 0;
  let resolveRequest;
  const pendingRequest = new Promise((resolve) => { resolveRequest = resolve; });
  const controller = createCameraPreviewController({
    requestPreview: async () => {
      requestCount += 1;
      return pendingRequest;
    },
    previewState,
    setMessage: () => {},
  });

  const first = controller.capture(1);
  const duplicate = controller.capture(1);
  assert.equal(await duplicate, false);
  assert.equal(requestCount, 1);

  resolveRequest({ type: 'image/jpeg', size: 20 });
  await flush();
  previewState.imageLoaded('blob:preview-single-flight-1');
  assert.equal(await first, true);
  assert.equal(requestCount, 1);
});

test('a 200 JPEG blob survives image load and a dashboard rerender without its spinner', async () => {
  const { previewState, renders } = createPreviewHarness('preview-rerender');
  const controller = createCameraPreviewController({
    requestPreview: async () => ({ type: 'image/jpeg', size: 20 }),
    previewState,
    setMessage: () => {},
  });

  const capture = controller.capture(1);
  await flush();
  previewState.imageLoaded('blob:preview-rerender-1');
  assert.equal(await capture, true);
  previewState.render();

  assert.deepEqual(renders.at(-1), {
    status: 'success',
    url: 'blob:preview-rerender-1',
    pendingUrl: null,
    previousUrl: null,
    error: '',
    imageVisible: true,
    spinnerVisible: false,
  });
});

test('dashboard integration renders the preview from persisted success state', async () => {
  const dashboard = await readFile(new URL('./dashboard.js', import.meta.url), 'utf8');

  assert.match(dashboard, /createCameraPreviewState\(\{ animalId, render: renderPreview \}\)/);
  assert.match(dashboard, /preview\.dataset\.status = snapshot\.status/);
  assert.match(dashboard, /snapshot\.pendingUrl === snapshot\.url/);
  assert.match(dashboard, /previewState\.imageLoaded\(snapshot\.url\)/);
  assert.match(dashboard, /if \(isLoading\) \{/);
  assert.doesNotMatch(dashboard, /createCameraPreviewRenderer/);
});

test('a completed preview restores as success in a new dashboard renderer', async () => {
  const first = createPreviewHarness('preview-persisted');
  first.previewState.start();
  const firstImage = first.previewState.show({ type: 'image/jpeg', size: 20 });
  first.previewState.imageLoaded('blob:preview-persisted-1');
  await firstImage;

  const rerendered = createPreviewHarness('preview-persisted');
  rerendered.previewState.render();

  assert.equal(rerendered.renders.at(-1).status, 'success');
  assert.equal(rerendered.renders.at(-1).url, 'blob:preview-persisted-1');
  assert.equal(rerendered.renders.at(-1).imageVisible, true);
  assert.equal(rerendered.renders.at(-1).spinnerVisible, false);
});

test('the previous preview URL is revoked only after the replacement image has loaded', async () => {
  const { previewState, revoked } = createPreviewHarness('preview-replace');
  previewState.start();
  const first = previewState.show({ type: 'image/jpeg', size: 20 });
  previewState.imageLoaded('blob:preview-replace-1');
  await first;

  previewState.start();
  const second = previewState.show({ type: 'image/jpeg', size: 20 });
  assert.deepEqual(revoked, []);
  previewState.imageLoaded('blob:preview-replace-2');
  await second;

  assert.deepEqual(revoked, ['blob:preview-replace-1']);
});
