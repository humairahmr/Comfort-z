/** Run an async control action without touching a control removed by a rerender. */
export async function runAsyncControl(control, action) {
  control.disabled = true;
  try {
    return await action();
  } finally {
    if (control.isConnected) control.disabled = false;
  }
}
