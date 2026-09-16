import { EventEmitter } from "./EventEmitter";
import { PendingUploadStore } from "./db";
import type { StoredAudioChunk, UploadJob } from "../types";

export interface UploadQueueEvents extends Record<string, unknown> {
  jobUpdated: UploadJob;
}

export interface UploadQueueOptions {
  maxRetries: number;
  retryBaseMs: number;
  uploadChunk: (chunk: StoredAudioChunk) => Promise<void>;
  isOnline?: () => boolean;
  scheduleRetry?: (fn: () => void, delayMs: number) => void;
}

function makeJobId(chunk: StoredAudioChunk): string {
  return `${chunk.sessionId}:${chunk.sequence}`;
}

/**
 * Upload queue with retry + exponential backoff (Queue pattern), backed by
 * the pendingUploads IndexedDB store so jobs survive reload/backgrounding/
 * tab closure (T15.2, T15.6).
 */
export class UploadQueue {
  private emitter = new EventEmitter<UploadQueueEvents>();
  private processing = false;

  constructor(private readonly options: UploadQueueOptions) {}

  on<K extends keyof UploadQueueEvents>(
    event: K,
    listener: (payload: UploadQueueEvents[K]) => void,
  ): () => void {
    return this.emitter.on(event, listener);
  }

  private isOnline(): boolean {
    if (this.options.isOnline) return this.options.isOnline();
    return typeof navigator === "undefined" || navigator.onLine !== false;
  }

  async enqueue(chunk: StoredAudioChunk): Promise<UploadJob> {
    const job: UploadJob = {
      id: makeJobId(chunk),
      sessionId: chunk.sessionId,
      chunk,
      status: "pending",
      retries: 0,
    };
    await PendingUploadStore.put(job);
    this.emitter.emit("jobUpdated", job);
    void this.processQueue();
    return job;
  }

  /** Reload jobs from IndexedDB (e.g. on app open after tab closure) and resume. */
  async resume(): Promise<void> {
    await this.processQueue();
  }

  async processQueue(): Promise<void> {
    if (this.processing) return;
    this.processing = true;
    try {
      if (!this.isOnline()) return;
      const jobs = await PendingUploadStore.listPendingOrFailed();
      for (const job of jobs) {
        await this.attemptUpload(job);
      }
    } finally {
      this.processing = false;
    }
  }

  private async attemptUpload(job: UploadJob): Promise<void> {
    if (!this.isOnline()) return;
    const uploading: UploadJob = { ...job, status: "uploading" };
    await PendingUploadStore.put(uploading);
    this.emitter.emit("jobUpdated", uploading);

    try {
      await this.options.uploadChunk(job.chunk);
      const completed: UploadJob = { ...uploading, status: "completed" };
      await PendingUploadStore.put(completed);
      this.emitter.emit("jobUpdated", completed);
    } catch (err) {
      const retries = job.retries + 1;
      const error = err instanceof Error ? err.message : String(err);
      if (retries > this.options.maxRetries) {
        const failed: UploadJob = { ...uploading, status: "failed", retries, error };
        await PendingUploadStore.put(failed);
        this.emitter.emit("jobUpdated", failed);
        return;
      }
      const retryable: UploadJob = { ...uploading, status: "pending", retries, error };
      await PendingUploadStore.put(retryable);
      this.emitter.emit("jobUpdated", retryable);

      const delay = this.options.retryBaseMs * 2 ** (retries - 1);
      const schedule = this.options.scheduleRetry ?? ((fn: () => void, ms: number) => setTimeout(fn, ms));
      schedule(() => {
        void this.processQueue();
      }, delay);
    }
  }

  async manualRetry(jobId: string): Promise<void> {
    const job = await PendingUploadStore.get(jobId);
    if (!job) return;
    await PendingUploadStore.put({ ...job, status: "pending", error: undefined });
    await this.processQueue();
  }

  async clear(sessionId: string): Promise<void> {
    const jobs = await PendingUploadStore.listBySession(sessionId);
    await Promise.all(jobs.map((job) => PendingUploadStore.delete(job.id)));
  }
}
