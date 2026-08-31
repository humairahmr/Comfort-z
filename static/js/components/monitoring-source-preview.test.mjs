import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import {
  initializeMonitoringVideoPreview,
  monitoringSourcePreviewUrl,
  supportsMonitoringVideoPreview,
} from './monitoring-source-preview.mjs';

test('only configured video profiles receive an animal-specific preview URL', () => {
  assert.equal(
    supportsMonitoringVideoPreview({ source_type: 'video', source_reference: 'gs://private/raku.mp4' }),
    true,
  );
  assert.equal(supportsMonitoringVideoPreview({ source_type: 'webcam', source_reference: 0 }), false);
  assert.equal(supportsMonitoringVideoPreview({ source_type: null, source_reference: null }), false);
  assert.equal(
    monitoringSourcePreviewUrl('raku/demo'),
    '/animals/raku%2Fdemo/monitoring-source-preview',
  );
});

test('video preview failure reveals the existing honest fallback', () => {
  let errorHandler;
  const video = {
    hidden: false,
    src: '',
    loadCalls: 0,
    addEventListener(name, handler, options) {
      assert.equal(name, 'error');
      assert.deepEqual(options, { once: true });
      errorHandler = handler;
    },
    load() { this.loadCalls += 1; },
  };
  const fallback = { hidden: true };
  const context = { hidden: false };

  initializeMonitoringVideoPreview({ video, fallback, context, url: '/preview' });
  assert.equal(video.src, '/preview');
  assert.equal(video.loadCalls, 1);
  errorHandler();
  assert.equal(video.hidden, true);
  assert.equal(context.hidden, true);
  assert.equal(fallback.hidden, false);
});

test('dashboard renders truthful video preview copy without changing webcam or source-less states', async () => {
  const [dashboard, css] = await Promise.all([
    readFile(new URL('./dashboard.js', import.meta.url), 'utf8'),
    readFile(new URL('../../css/components.css', import.meta.url), 'utf8'),
  ]);

  assert.match(dashboard, /<video[\s\S]*controls[\s\S]*muted[\s\S]*playsinline[\s\S]*preload="metadata"/);
  assert.match(dashboard, /Monitoring source preview/);
  assert.match(dashboard, /Playback is for reference\. Comfort-z samples the source independently\./);
  assert.match(dashboard, /Monitoring source not connected/);
  assert.match(dashboard, /Camera connected/);
  assert.match(dashboard, /Live playback is not shown here/);
  assert.doesNotMatch(dashboard, /gs:\/\//);
  assert.match(css, /\.stage-viewport-split[^}]*height:\s*400px[^}]*min-height:\s*0/);
  assert.match(css, /\.stage-video-player[^}]*width:\s*100%[^}]*height:\s*100%[^}]*max-height:\s*100%[^}]*object-fit:\s*contain[^}]*object-position:\s*center/);
  assert.match(css, /\.stage-telemetry-pane[^}]*min-height:\s*0[^}]*overflow-y:\s*auto/);
  assert.match(css, /\.stage-viewport-split\s*\{[^}]*height:\s*auto/);
  assert.match(css, /\.stage-media-pane\s*\{[^}]*height:\s*clamp\(220px,56\.25vw,360px\)/);
});
