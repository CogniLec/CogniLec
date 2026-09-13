import { openDB, type IDBPDatabase, type DBSchema } from "idb";
import type { RecordingSession, StoredAudioChunk, UploadJob } from "../types";

// IndexedDB ring buffer schema, per S15 spec section 2.
// DB name: lis-recorder
// Object stores:
//   chunks: keyPath='id', indexes on sessionId, status
//   sessions: keyPath='id'
//   pendingUploads: keyPath='id', index on sessionId

interface LisRecorderDB extends DBSchema {
  chunks: {
    key: string;
    value: StoredAudioChunk & { status: "buffered" | "uploaded" };
    indexes: { sessionId: string; status: string };
  };
  sessions: {
    key: string;
    value: RecordingSession;
  };
  pendingUploads: {
    key: string;
    value: UploadJob;
    indexes: { sessionId: string };
  };
}

const DB_NAME = "lis-recorder";
const DB_VERSION = 1;

let dbPromise: Promise<IDBPDatabase<LisRecorderDB>> | null = null;

export function getDb(): Promise<IDBPDatabase<LisRecorderDB>> {
  if (!dbPromise) {
    dbPromise = openDB<LisRecorderDB>(DB_NAME, DB_VERSION, {
      upgrade(db) {
        if (!db.objectStoreNames.contains("chunks")) {
          const chunkStore = db.createObjectStore("chunks", { keyPath: "id" });
          chunkStore.createIndex("sessionId", "sessionId");
          chunkStore.createIndex("status", "status");
        }
        if (!db.objectStoreNames.contains("sessions")) {
          db.createObjectStore("sessions", { keyPath: "id" });
        }
        if (!db.objectStoreNames.contains("pendingUploads")) {
          const uploadStore = db.createObjectStore("pendingUploads", { keyPath: "id" });
          uploadStore.createIndex("sessionId", "sessionId");
        }
      },
    });
  }
  return dbPromise;
}

/** Reset the cached DB handle. Intended for tests only. */
export function _resetDbForTests(): void {
  dbPromise = null;
}

export const ChunkStore = {
  async put(chunk: StoredAudioChunk, status: "buffered" | "uploaded" = "buffered"): Promise<void> {
    const db = await getDb();
    await db.put("chunks", { ...chunk, status });
  },
  async get(id: string): Promise<StoredAudioChunk | undefined> {
    const db = await getDb();
    return db.get("chunks", id);
  },
  async listBySession(sessionId: string): Promise<StoredAudioChunk[]> {
    const db = await getDb();
    return db.getAllFromIndex("chunks", "sessionId", sessionId);
  },
  async countAll(): Promise<number> {
    const db = await getDb();
    return db.count("chunks");
  },
  async deleteOldestCompleted(limit: number): Promise<number> {
    const db = await getDb();
    const tx = db.transaction("chunks", "readwrite");
    const index = tx.store.index("status");
    let cursor = await index.openCursor(IDBKeyRange.only("uploaded"));
    let deleted = 0;
    while (cursor && deleted < limit) {
      await cursor.delete();
      deleted += 1;
      cursor = await cursor.continue();
    }
    await tx.done;
    return deleted;
  },
};

export const SessionStore = {
  async put(session: RecordingSession): Promise<void> {
    const db = await getDb();
    await db.put("sessions", session);
  },
  async get(id: string): Promise<RecordingSession | undefined> {
    const db = await getDb();
    return db.get("sessions", id);
  },
  async all(): Promise<RecordingSession[]> {
    const db = await getDb();
    return db.getAll("sessions");
  },
};

export const PendingUploadStore = {
  async put(job: UploadJob): Promise<void> {
    const db = await getDb();
    await db.put("pendingUploads", job);
  },
  async get(id: string): Promise<UploadJob | undefined> {
    const db = await getDb();
    return db.get("pendingUploads", id);
  },
  async delete(id: string): Promise<void> {
    const db = await getDb();
    await db.delete("pendingUploads", id);
  },
  async listBySession(sessionId: string): Promise<UploadJob[]> {
    const db = await getDb();
    return db.getAllFromIndex("pendingUploads", "sessionId", sessionId);
  },
  async listPendingOrFailed(): Promise<UploadJob[]> {
    const db = await getDb();
    const all = await db.getAll("pendingUploads");
    return all.filter((job) => job.status === "pending" || job.status === "failed");
  },
  async all(): Promise<UploadJob[]> {
    const db = await getDb();
    return db.getAll("pendingUploads");
  },
};

/** IndexedDB quota-guard: evict oldest completed uploads if buffer is too large. */
export async function enforceQuota(maxChunks: number): Promise<void> {
  const total = await ChunkStore.countAll();
  if (total > maxChunks) {
    await ChunkStore.deleteOldestCompleted(total - maxChunks);
  }
}
