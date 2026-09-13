import { describe, it, expect, beforeEach, vi } from "vitest";
import { UploadQueue } from "../../../src/client/src/services/UploadQueue";
import { PendingUploadStore, getDb, _resetDbForTests } from "../../../src/client/src/services/db";

async function clearAllStores(): Promise<void> {
  const db = await getDb();
  await Promise.all([
    db.clear("chunks"),
    db.clear("sessions"),
    db.clear("pendingUploads"),
  ]);
}
import type { StoredAudioChunk } from "../../../src/client/src/types";

function makeChunk(sessionId: string, sequence: number): StoredAudioChunk {
  return {
    id: `${sessionId}:${sequence}`,
    sessionId,
    sequence,
    blob: new Blob([new Uint8Array(10)]),
    startTime: sequence * 25_000,
    endTime: sequence * 25_000 + 30_000,
    sampleRate: 48000,
    createdAt: Date.now(),
  };
}

describe("UploadQueue (T15.2 network disconnect / resume, retry backoff)", () => {
  beforeEach(async () => {
    _resetDbForTests();
    // fake-indexeddb persists data across tests within the same module; wipe
    // the stores so each test starts from a clean ring buffer.
    await clearAllStores();
  });

  it("buffers to IndexedDB while offline and uploads once back online", async () => {
    let online = false;
    const uploadChunk = vi.fn().mockResolvedValue(undefined);
    const queue = new UploadQueue({
      maxRetries: 5,
      retryBaseMs: 10,
      getPresignedUrl: vi.fn().mockResolvedValue("https://upload.example/chunk"),
      uploadChunk,
      isOnline: () => online,
    });

    const chunk = makeChunk("session-x", 0);
    await queue.enqueue(chunk);

    // Still offline: nothing uploaded, but the job persists in IndexedDB.
    expect(uploadChunk).not.toHaveBeenCalled();
    const pendingWhileOffline = await PendingUploadStore.listBySession("session-x");
    expect(pendingWhileOffline).toHaveLength(1);
    expect(pendingWhileOffline[0].status).toBe("pending");

    // Network resumes.
    online = true;
    await queue.resume();

    expect(uploadChunk).toHaveBeenCalledTimes(1);
    const jobs = await PendingUploadStore.listBySession("session-x");
    expect(jobs[0].status).toBe("completed");
  });

  it("retries with exponential backoff and eventually marks failed after max retries", async () => {
    const uploadChunk = vi.fn().mockRejectedValue(new Error("network error"));
    const delays: number[] = [];
    const queue = new UploadQueue({
      maxRetries: 2,
      retryBaseMs: 5,
      getPresignedUrl: vi.fn().mockResolvedValue("https://upload.example/chunk"),
      uploadChunk,
      isOnline: () => true,
      // Run "retries" synchronously-ish (setTimeout 0) so the test doesn't
      // depend on real wall-clock backoff durations, while still recording
      // the requested delay to assert it grows exponentially.
      scheduleRetry: (fn, ms) => {
        delays.push(ms);
        setTimeout(fn, 0);
      },
    });

    const chunk = makeChunk("session-y", 0);
    const failed = new Promise<void>((resolve) => {
      queue.on("jobUpdated", (job) => {
        if (job.status === "failed") resolve();
      });
    });
    await queue.enqueue(chunk);
    await failed;

    const jobs = await PendingUploadStore.listBySession("session-y");
    expect(jobs[0].status).toBe("failed");
    expect(jobs[0].retries).toBeGreaterThan(2);
    expect(delays).toEqual([5, 10]);
  });

  it("resumes buffered jobs left in IndexedDB from a prior tab session (T15.6)", async () => {
    const chunk = makeChunk("session-z", 0);
    await PendingUploadStore.put({
      id: chunk.id,
      sessionId: "session-z",
      chunk,
      status: "pending",
      retries: 0,
    });

    const uploadChunk = vi.fn().mockResolvedValue(undefined);
    const queue = new UploadQueue({
      maxRetries: 5,
      retryBaseMs: 10,
      getPresignedUrl: vi.fn().mockResolvedValue("https://upload.example/chunk"),
      uploadChunk,
      isOnline: () => true,
    });

    await queue.resume();

    expect(uploadChunk).toHaveBeenCalledTimes(1);
    const jobs = await PendingUploadStore.listBySession("session-z");
    expect(jobs[0].status).toBe("completed");
  });

  it("allows manual retry of a failed job", async () => {
    const chunk = makeChunk("session-w", 0);
    await PendingUploadStore.put({
      id: chunk.id,
      sessionId: "session-w",
      chunk,
      status: "failed",
      retries: 6,
      error: "gave up",
    });

    const uploadChunk = vi.fn().mockResolvedValue(undefined);
    const queue = new UploadQueue({
      maxRetries: 5,
      retryBaseMs: 10,
      getPresignedUrl: vi.fn().mockResolvedValue("https://upload.example/chunk"),
      uploadChunk,
      isOnline: () => true,
    });

    await queue.manualRetry(chunk.id);
    const jobs = await PendingUploadStore.listBySession("session-w");
    expect(jobs[0].status).toBe("completed");
  });
});
