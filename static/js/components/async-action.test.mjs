import assert from 'node:assert/strict';
import test from 'node:test';

import { runAsyncControl } from './async-action.mjs';

function trackedControl() {
  let connected = true;
  let disabled = false;
  const writes = [];
  return {
    get isConnected() { return connected; },
    set isConnected(value) { connected = value; },
    get disabled() { return disabled; },
    set disabled(value) {
      if (!connected) throw new TypeError('detached control was mutated');
      disabled = value;
      writes.push(value);
    },
    writes,
  };
}

test('an async dashboard action does not mutate its control after a rerender detaches it', async () => {
  const control = trackedControl();

  const result = await runAsyncControl(control, async () => {
    control.isConnected = false;
    return 'refreshed';
  });

  assert.equal(result, 'refreshed');
  assert.deepEqual(control.writes, [true]);
});

test('a still-mounted control is re-enabled and action failures are not swallowed', async () => {
  const control = trackedControl();
  const failure = new Error('request failed');

  await assert.rejects(runAsyncControl(control, async () => { throw failure; }), failure);

  assert.deepEqual(control.writes, [true, false]);
  assert.equal(control.disabled, false);
});
