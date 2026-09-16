import { CONFIG } from "../config";
import { getAccessToken } from "./auth";
import type { Flashcard, FsrsRating, MaterialUploadResult, StudyProgress, Subject } from "../types";

// Thin fetch wrappers around the backend contracts documented in S15 spec
// section 5 (backed by S07 subjects/sessions routes). Kept minimal and
// mockable — see tests/client/services/api.test.ts.

export interface SubjectListResponse {
  items: Array<{ id: string; name: string; description: string | null }>;
  total: number;
}

export interface SessionCreateResponse {
  id: string;
  subject_id: string;
  status: string;
}

/**
 * Carries the HTTP status alongside the message so callers can tell an
 * expected "not found yet" 404 (e.g. no flashcards for a brand-new subject)
 * apart from a genuine failure, instead of showing the same raw
 * "API request failed: 404 Not Found" text for both.
 */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    statusText: string,
  ) {
    super(`API request failed: ${status} ${statusText}`);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getAccessToken();
  const res = await fetch(`${CONFIG.apiBaseUrl}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    ...init,
  });
  if (!res.ok) {
    throw new ApiError(res.status, res.statusText);
  }
  return (await res.json()) as T;
}

export async function fetchSubjects(): Promise<Subject[]> {
  const data = await request<SubjectListResponse>("/api/v1/subjects/");
  return data.items.map((item) => ({
    id: item.id,
    name: item.name,
    description: item.description,
  }));
}

export async function createSubject(name: string): Promise<Subject> {
  return request<Subject>("/api/v1/subjects/", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

export async function createSession(
  subjectId: string,
  sessionType: "content" | "syllabus" | "mixed" = "content",
): Promise<SessionCreateResponse> {
  return request<SessionCreateResponse>("/api/v1/sessions/", {
    method: "POST",
    body: JSON.stringify({ subject_id: subjectId, session_type: sessionType }),
  });
}

/**
 * Uploads one audio chunk directly to the real, working backend endpoint
 * (src/api/routes/chunks.py POST /sessions/{id}/chunks) as multipart
 * form data. A separate presigned-URL flow used to exist here
 * (`fetchPresignedUploadUrl`/`uploadChunkToPresignedUrl`), calling
 * `/api/v1/sessions/{id}/chunks/{sequence}/presigned-url` -- a route that
 * was never actually implemented server-side, so every chunk upload
 * 404'd silently (confirmed live). This replaces that with the endpoint
 * that genuinely exists, does auth/ownership checks, and pushes the
 * chunk onto the ASR pipeline's Valkey stream.
 *
 * No `Content-Type` header is set deliberately, same reason as
 * `uploadMaterial` below: the browser must set its own multipart
 * boundary, which the shared `request()` helper's hardcoded
 * `application/json` header would break.
 */
export async function uploadSessionChunk(chunk: {
  sessionId: string;
  sequence: number;
  startTime: number;
  endTime: number;
  blob: Blob;
  isFinal: boolean;
}): Promise<void> {
  const token = getAccessToken();
  const body = new FormData();
  body.append("sequence", String(chunk.sequence));
  body.append("timestamp_ms", String(Math.round(chunk.startTime)));
  body.append("duration_ms", String(Math.max(1, Math.round(chunk.endTime - chunk.startTime))));
  body.append("is_final", chunk.isFinal ? "true" : "false");
  body.append("chunk", chunk.blob, `${chunk.sequence}.webm`);

  const res = await fetch(`${CONFIG.apiBaseUrl}/api/v1/sessions/${chunk.sessionId}/chunks`, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    body,
  });
  if (!res.ok) {
    throw new Error(`Chunk upload failed: ${res.status} ${res.statusText}`);
  }
}

// Manual-review-app: study/quiz loop over S58's flashcards + FSRS
// scheduling, backed by src/api/routes/study.py.

export async function fetchNextFlashcard(subjectId: string): Promise<Flashcard> {
  return request<Flashcard>(`/api/v1/subjects/${subjectId}/flashcards/next`);
}

export async function seedFlashcard(
  subjectId: string,
  topicLabel: string,
  front: string,
  back: string,
): Promise<Flashcard> {
  const params = new URLSearchParams({ topic_label: topicLabel, front, back });
  return request<Flashcard>(`/api/v1/subjects/${subjectId}/flashcards/seed?${params}`, {
    method: "POST",
  });
}

export async function reviewFlashcard(
  subjectId: string,
  flashcardId: string,
  rating: FsrsRating,
  selfCorrect: boolean,
  consentForTraining: boolean,
): Promise<{ flashcard: Flashcard; correction_recorded: boolean }> {
  return request(`/api/v1/subjects/${subjectId}/flashcards/${flashcardId}/review`, {
    method: "POST",
    body: JSON.stringify({
      rating,
      self_correct: selfCorrect,
      consent_for_training: consentForTraining,
    }),
  });
}

export async function fetchStudyProgress(subjectId: string): Promise<StudyProgress> {
  return request<StudyProgress>(`/api/v1/subjects/${subjectId}/study/progress`);
}

/**
 * Uploads a syllabus/reference document — PDF, image (PNG/JPG), TXT, or MD
 * (src/services/docling/parser.py `detect_format`) — for a subject. No
 * `Content-Type` header is set here deliberately: the browser must set its
 * own `multipart/form-data` boundary, which the shared `request()` helper's
 * hardcoded `application/json` header would break.
 */
export async function uploadMaterial(subjectId: string, file: File): Promise<MaterialUploadResult> {
  const token = getAccessToken();
  const body = new FormData();
  body.append("file", file);

  const res = await fetch(`${CONFIG.apiBaseUrl}/api/v1/subjects/${subjectId}/syllabus`, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    body,
  });
  if (!res.ok) {
    throw new Error(`Upload failed: ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as MaterialUploadResult;
}
