import "@testing-library/jest-dom/vitest";
import "fake-indexeddb/auto";

// jsdom does not implement MediaRecorder / getUserMedia; individual tests
// provide fakes where needed. Provide safe defaults so components that
// merely check `Recorder.isSupported()` don't throw during unrelated tests.
if (typeof (globalThis as { MediaRecorder?: unknown }).MediaRecorder === "undefined") {
  class DefaultFakeMediaRecorder {
    static isTypeSupported(): boolean {
      return true;
    }
    state: "inactive" | "recording" = "inactive";
    mimeType = "audio/webm;codecs=opus";
    ondataavailable: ((event: { data: Blob }) => void) | null = null;
    onstop: (() => void) | null = null;
    onerror: (() => void) | null = null;

    start(): void {
      this.state = "recording";
    }

    stop(): void {
      this.state = "inactive";
      this.ondataavailable?.({ data: new Blob([new Uint8Array(16)]) });
      this.onstop?.();
    }
  }
  (globalThis as unknown as { MediaRecorder: unknown }).MediaRecorder = DefaultFakeMediaRecorder;
}

if (!("mediaDevices" in navigator)) {
  Object.defineProperty(navigator, "mediaDevices", {
    value: { getUserMedia: async () => ({ getTracks: () => [] }) },
    configurable: true,
  });
}
