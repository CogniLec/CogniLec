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
  // True only for the chunk emitted right after Recorder.stop() was
  // called. The backend's ASR worker only finalizes a session
  // (transitions it to a "transcribed" state so notes/flashcards can be
  // generated) when it processes a chunk with this flag set -- without
  // it, a session's audio is uploaded and transcribed but the pipeline
  // has no signal that recording is actually over.
  isFinal: boolean;
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

// Manual-review-app: auth + study/quiz loop types (S12 auth, S46 notes,
// S58 flashcards/FSRS, S65 corrections).

export interface AuthUser {
  id: string;
  email: string;
  is_active: boolean;
}

export interface Flashcard {
  id: string;
  subject_id: string;
  topic_label: string;
  front: string;
  back: string;
  due_at: string;
  last_review_at: string | null;
}

// fsrs.Rating: 1=Again, 2=Hard, 3=Good, 4=Easy.
export type FsrsRating = 1 | 2 | 3 | 4;

export interface ReviewOutcome {
  flashcard_id: string;
  rating: number;
  reviewed_at: string;
}

export interface StudyProgress {
  subject_id: string;
  total_reviews: number;
  correct_reviews: number;
  accuracy: number;
  recent_outcomes: ReviewOutcome[];
}

// Lets the frontend poll whether a just-recorded session's notes/
// flashcards are ready instead of guessing (docs/gaps.md #33f) --
// src/api/routes/study.py GET /subjects/{id}/study/status.
export interface StudyStatus {
  subject_id: string;
  session_id: string | null;
  status: string | null;
  notes_ready: boolean;
  flashcard_count: number;
  failure_reason: string | null;
}

// S51 syllabus/material upload (PDF, image, TXT, MD) — src/api/routes/syllabus_upload.py.
export interface MaterialUploadResult {
  upload_id: string;
  status: string;
  items_extracted: number | null;
  message: string;
  error_details: string | null;
}
