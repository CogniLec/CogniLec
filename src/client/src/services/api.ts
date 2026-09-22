import { CONFIG } from "../config";
import { getAccessToken, refreshAccessToken } from "./auth";
import type {
  Flashcard,
  FsrsRating,
  MaterialUploadResult,
  StudyProgress,
  StudyStatus,
  Subject,
} from "../types";

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
    /** FastAPI's `{"detail": "..."}` body text, when the response had one
     * and it parsed as JSON with a string `detail` -- e.g. "No flashcards
     * could be generated -- this subject has no persisted notes/topics
     * yet." for a 409 on flashcard generation. Callers that want that
     * specific text instead of the generic "API request failed: 409
     * Conflict" should show this when present (see friendlyErrorMessage). */
    public readonly detail?: string,
  ) {
    super(`API request failed: ${status} ${statusText}`);
    this.name = "ApiError";
  }
}

/**
 * Attaches the current access token and retries once on a 401 after a
 * silent token refresh, instead of every caller independently hitting a
 * raw "API request failed: 401 Unauthorized" the moment the access token
 * expires mid-session (docs/gaps.md #33h). Shared by `request()` below and
 * the three bespoke upload functions, which used to build their own
 * `Authorization` header inline and skip this entirely -- an
 * absent/expired token there sent the request with NO auth header at all.
 */
async function authorizedFetch(
  url: string,
  init: RequestInit,
  isRetry = false,
): Promise<Response> {
  const token = getAccessToken();
  const res = await fetch(url, {
    ...init,
    headers: {
      ...init.headers,
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  });
  if (res.status === 401 && !isRetry) {
    try {
      await refreshAccessToken();
    } catch {
      return res;
    }
    return authorizedFetch(url, init, true);
  }
  return res;
}

/**
 * Multipart upload via XMLHttpRequest (not `fetch`) so `onProgress` can
 * report real upload percentage -- previously `uploadMaterial`/
 * `uploadAudioFile` used plain `fetch`, which has no upload-progress hook,
 * so a large file's only feedback was a static "Uploading…" label that
 * looked like a hang (docs/gaps.md #33j). Mirrors `authorizedFetch`'s
 * 401-refresh-and-retry-once behavior so this transport isn't a second,
 * divergent auth path.
 */
function xhrUpload<T>(
  url: string,
  body: FormData,
  onProgress?: (fraction: number) => void,
  isRetry = false,
): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    const token = getAccessToken();
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);

    xhr.upload.onprogress = (event) => {
      if (onProgress && event.lengthComputable) {
        onProgress(event.loaded / event.total);
      }
    };

    xhr.onload = () => {
      if (xhr.status === 401 && !isRetry) {
        refreshAccessToken()
          .then(() => xhrUpload<T>(url, body, onProgress, true))
          .then(resolve, reject);
        return;
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText) as T);
        } catch {
          reject(new Error("Malformed response from server"));
        }
      } else {
        reject(new ApiError(xhr.status, xhr.statusText));
      }
    };
    xhr.onerror = () => reject(new Error("Network error during upload"));

    xhr.send(body);
  });
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await authorizedFetch(`${CONFIG.apiBaseUrl}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail: string | undefined;
    try {
      const body: unknown = await res.json();
      if (body && typeof body === "object" && typeof (body as { detail?: unknown }).detail === "string") {
        detail = (body as { detail: string }).detail;
      }
    } catch {
      // Non-JSON or empty error body -- fall back to the generic message.
    }
    throw new ApiError(res.status, res.statusText, detail);
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
  const body = new FormData();
  body.append("sequence", String(chunk.sequence));
  body.append("timestamp_ms", String(Math.round(chunk.startTime)));
  body.append("duration_ms", String(Math.max(1, Math.round(chunk.endTime - chunk.startTime))));
  body.append("is_final", chunk.isFinal ? "true" : "false");
  body.append("chunk", chunk.blob, `${chunk.sequence}.webm`);

  const res = await authorizedFetch(`${CONFIG.apiBaseUrl}/api/v1/sessions/${chunk.sessionId}/chunks`, {
    method: "POST",
    body,
  });
  if (!res.ok) {
    throw new Error(`Chunk upload failed: ${res.status} ${res.statusText}`);
  }
}

export interface AudioFileUploadResult {
  session_id: string;
  filename: string;
  total_chunks: number;
  status: string;
  message: string;
}

/**
 * Uploads an audio or video file (MP3, WAV, M4A, FLAC, OGG, WebM, AAC,
 * WMA, MP4, MOV, MKV) to an existing session. The server splits it into
 * 30s chunks and feeds them into the preprocessing → ASR pipeline. For a
 * video container, only its audio track is extracted.
 */
export async function uploadAudioFile(
  sessionId: string,
  file: File,
  onProgress?: (fraction: number) => void,
): Promise<AudioFileUploadResult> {
  const body = new FormData();
  body.append("file", file);
  return xhrUpload<AudioFileUploadResult>(
    `${CONFIG.apiBaseUrl}/api/v1/sessions/${sessionId}/audio-file`,
    body,
    onProgress,
  );
}

// Manual-review-app: study/quiz loop over S58's flashcards + FSRS
// scheduling, backed by src/api/routes/study.py.

export async function fetchNextFlashcard(subjectId: string): Promise<Flashcard> {
  return request<Flashcard>(`/api/v1/subjects/${subjectId}/flashcards/next`);
}

// Generates real flashcards from a subject's already-persisted notes via
// the LLM (src/services/study/flashcards.py). Replaces the old
// seedFlashcard manual-entry function (removed 2026-09-17) -- flashcards
// are never hand-typed now, only generated from real note content.
export async function generateFlashcards(subjectId: string): Promise<{ items: Flashcard[] }> {
  return request<{ items: Flashcard[] }>(`/api/v1/subjects/${subjectId}/flashcards/generate`, {
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

// Polling target for the "Generating your notes..." banner -- see
// src/client/src/hooks/useStudyStatus.ts.
export async function fetchStudyStatus(subjectId: string): Promise<StudyStatus> {
  return request<StudyStatus>(`/api/v1/subjects/${subjectId}/study/status`);
}

/**
 * Uploads a syllabus/reference document — PDF, image (PNG/JPG), TXT, or MD
 * (src/services/docling/parser.py `detect_format`) — for a subject. No
 * `Content-Type` header is set here deliberately: the browser must set its
 * own `multipart/form-data` boundary, which the shared `request()` helper's
 * hardcoded `application/json` header would break.
 */
export async function uploadMaterial(
  subjectId: string,
  file: File,
  onProgress?: (fraction: number) => void,
): Promise<MaterialUploadResult> {
  const body = new FormData();
  body.append("file", file);
  return xhrUpload<MaterialUploadResult>(
    `${CONFIG.apiBaseUrl}/api/v1/subjects/${subjectId}/syllabus`,
    body,
    onProgress,
  );
}
