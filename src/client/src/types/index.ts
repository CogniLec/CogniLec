// Domain types per S15 spec section 2.

export interface Subject {
  id: string;
  name: string;
  description: string | null;
}

export type RecordingStatus = "idle" | "recording" | "stopped";

export type AppState =
  | "IDLE"
  | "CONSENT_REQUIRED"
  | "NO_CONSENT"
  | "RECORDING"
  | "PAUSED"
  | "STOPPED";

export interface AudioChunk {
  sessionId: string;
  sequence: number;
  blob: Blob;
  startTime: number; // ms since session start
  endTime: number;
  sampleRate: number;
  createdAt: number; // Date.now()
}

/** AudioChunk persisted in IndexedDB, keyed by a stable id. */
export interface StoredAudioChunk extends AudioChunk {
  id: string;
}

export type UploadStatus = "pending" | "uploading" | "completed" | "failed";

export interface UploadJob {
  id: string;
  sessionId: string;
  chunk: StoredAudioChunk;
  status: UploadStatus;
  retries: number;
  uploadUrl?: string;
  error?: string;
}

export interface RecordingSession {
  id: string;
  subjectId: string;
  subjectName: string;
  status: RecordingStatus;
  startedAt: number;
  elapsedMs: number;
  chunkCount: number;
  consentAcknowledged: boolean;
}

export interface ConsentRecord {
  sessionId: string;
  acknowledgedAt: number;
  consentVersion: string; // "v1.0"
  userId: string;
}
