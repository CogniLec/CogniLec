import { describe, it, expect, beforeEach } from "vitest";
import {
  ChunkStore,
  SessionStore,
  PendingUploadStore,
  enforceQuota,
  getDb,
  _resetDbForTests,
} from "../../../src/client/src/services/db";

async function clearAllStores(): Promise<void> {
  const db = await getDb();
  await Promise.all([
    db.clear("chunks"),
    db.clear("sessions"),
    db.clear("pendingUploads"),
  ]);
}
import type { StoredAudioChunk, UploadJob } from "../../../src/client/src/types";

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

describe("IndexedDB ring buffer (persistence across reload)", () => {
  beforeEach(async () => {
    _resetDbForTests();
    await clearAllStores();
  });

  it("persists chunks, sessions, and pending uploads (T15.2 / T15.6 buffering)", async () => {
    const chunk = makeChunk("session-a", 0);
    await ChunkStore.put(chunk, "buffered");

    const fetched = await ChunkStore.get(chunk.id);
    expect(fetched?.sessionId).toBe("session-a");

    await SessionStore.put({
      id: "session-a",
      subjectId: "subj-1",
      subjectName: "Physics",
      status: "recording",
      startedAt: Date.now(),
      elapsedMs: 0,
      chunkCount: 1,
      consentAcknowledged: true,
    });
    const session = await SessionStore.get("session-a");
    expect(session?.subjectName).toBe("Physics");

    const job: UploadJob = {
      id: chunk.id,
      sessionId: "session-a",
      chunk,
      status: "pending",
      retries: 0,
    };
    await PendingUploadStore.put(job);
    const pending = await PendingUploadStore.listBySession("session-a");
    expect(pending).toHaveLength(1);
    expect(pending[0].status).toBe("pending");
  });

  it("survives a simulated reload by reopening the same DB and reading prior data", async () => {
    const chunk = makeChunk("session-b", 0);
    await ChunkStore.put(chunk, "buffered");

    // Simulate "reload" by dropping the cached connection handle; idb will
    // reopen the same underlying database (fake-indexeddb persists for the
    // life of the test process, standing in for the browser's IndexedDB).
    _resetDbForTests();

    const chunks = await ChunkStore.listBySession("session-b");
    expect(chunks).toHaveLength(1);
  });

  it("evicts oldest completed chunks when quota is exceeded", async () => {
    for (let i = 0; i < 5; i += 1) {
      await ChunkStore.put(makeChunk("session-c", i), "uploaded");
    }
    await enforceQuota(2);
    const remaining = await ChunkStore.listBySession("session-c");
    expect(remaining.length).toBeLessThanOrEqual(2);
  });
});
