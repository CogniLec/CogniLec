// Lets main.tsx's PWA-update reload (see main.tsx) know whether a
// recording is in progress, without needing a React context at module
// scope. Previously the reload was unconditional -- a deploy landing
// mid-recording would hard-reload the tab and lose all in-memory state
// with no warning (docs/gaps.md #33j).
let active = false;
const stopListeners = new Set<() => void>();

export function isRecordingActive(): boolean {
  return active;
}

export function setRecordingActive(value: boolean): void {
  active = value;
  if (!value) {
    const listeners = Array.from(stopListeners);
    stopListeners.clear();
    listeners.forEach((fn) => fn());
  }
}

/** Fires once, the next time recording stops. */
export function onceRecordingStops(fn: () => void): void {
  stopListeners.add(fn);
}
