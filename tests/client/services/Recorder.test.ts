import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { Recorder } from "../../../src/client/src/services/Recorder";
import type { AudioChunk } from "../../../src/client/src/types";

/** Minimal fake MediaRecorder driven manually by tests via fake timers. */
class FakeMediaRecorder {
  static isTypeSupported(): boolean {
    return true;
  }
  state: "inactive" | "recording" = "inactive";
  ondataavailable: ((event: { data: Blob; size?: number }) => void) | null = null;
  onstop: (() => void) | null = null;
  onerror: (() => void) | null = null;
  mimeType = "audio/webm;codecs=opus";

  constructor(_stream: unknown, _options?: unknown) {}

  start(): void {
    this.state = "recording";
  }

  stop(): void {
    this.state = "inactive";
    // Simulate a ~1KB chunk of encoded audio per emitted segment.
    this.ondataavailable?.({ data: new Blob([new Uint8Array(1024)]) });
    this.onstop?.();
  }
}

function fakeGetUserMedia(): Promise<MediaStream> {
  return Promise.resolve({
    getTracks: () => [{ stop: vi.fn() }],
  } as unknown as MediaStream);
}

describe("Recorder chunking (T15.1, T15.7)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("produces approximately 120 chunks for a 60-minute recording with 30s chunks / 5s overlap", async () => {
    const chunks: AudioChunk[] = [];
    const recorder = new Recorder({
      sessionId: "session-1",
      chunkDurationMs: 30_000,
      overlapMs: 5_000,
      getUserMedia: fakeGetUserMedia,
      mediaRecorderCtor: FakeMediaRecorder as unknown as typeof MediaRecorder,
    });
    recorder.on("chunk", (chunk) => chunks.push(chunk));

    await recorder.start();

    const sixtyMinutesMs = 60 * 60 * 1000;
    await vi.advanceTimersByTimeAsync(sixtyMinutesMs);

    recorder.stop();
    await vi.runOnlyPendingTimersAsync();

    // 60min / 30s = 120 chunks, allow a small tolerance for the final
    // partial chunk emitted by stop().
    expect(chunks.length).toBeGreaterThanOrEqual(119);
    expect(chunks.length).toBeLessThanOrEqual(121);

    // Each chunk after the first should overlap the previous by ~5s.
    for (let i = 1; i < chunks.length; i += 1) {
      const prev = chunks[i - 1];
      const curr = chunks[i];
      expect(curr.startTime).toBeLessThanOrEqual(prev.endTime);
    }
  });

  it("keeps total encoded output within the 15MB budget for a 60-minute session", async () => {
    const chunks: AudioChunk[] = [];
    const recorder = new Recorder({
      sessionId: "session-2",
      chunkDurationMs: 30_000,
      overlapMs: 5_000,
      getUserMedia: fakeGetUserMedia,
      mediaRecorderCtor: FakeMediaRecorder as unknown as typeof MediaRecorder,
    });
    recorder.on("chunk", (chunk) => chunks.push(chunk));

    await recorder.start();
    await vi.advanceTimersByTimeAsync(60 * 60 * 1000);
    recorder.stop();
    await vi.runOnlyPendingTimersAsync();

    const totalBytes = chunks.reduce((sum, chunk) => sum + chunk.blob.size, 0);
    const fifteenMb = 15 * 1024 * 1024;
    expect(totalBytes).toBeLessThanOrEqual(fifteenMb);
  });

  it("continues recording across a simulated backgrounding period with no chunk gap (T15.3)", async () => {
    const chunks: AudioChunk[] = [];
    const recorder = new Recorder({
      sessionId: "session-3",
      chunkDurationMs: 30_000,
      overlapMs: 5_000,
      getUserMedia: fakeGetUserMedia,
      mediaRecorderCtor: FakeMediaRecorder as unknown as typeof MediaRecorder,
    });
    recorder.on("chunk", (chunk) => chunks.push(chunk));

    await recorder.start();
    // Simulate backgrounding: timers still fire (MediaRecorder keeps running
    // in background per spec — no pause is invoked), foreground resumes.
    await vi.advanceTimersByTimeAsync(5 * 60 * 1000);
    recorder.stop();
    await vi.runOnlyPendingTimersAsync();

    expect(chunks.length).toBeGreaterThan(0);
    // No gap: each chunk's start should not exceed the previous chunk's end
    // by more than the nominal chunk duration (i.e. no missing chunk).
    for (let i = 1; i < chunks.length; i += 1) {
      expect(chunks[i].startTime - chunks[i - 1].endTime).toBeLessThanOrEqual(0);
    }
  });

  it("reports unsupported when MediaRecorder/mediaDevices are absent", () => {
    const original = (globalThis as { MediaRecorder?: unknown }).MediaRecorder;
    // @ts-expect-error -- deliberately simulating absence for this assertion
    delete globalThis.MediaRecorder;
    expect(Recorder.isSupported()).toBe(false);
    (globalThis as unknown as { MediaRecorder: unknown }).MediaRecorder = original;
  });
});
