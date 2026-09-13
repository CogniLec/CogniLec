// Central place for env-derived configuration (Vite convention: import.meta.env).

function readNumber(value: string | undefined, fallback: number): number {
  if (value === undefined || value === "") return fallback;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

export const CONFIG = {
  apiBaseUrl: (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "http://localhost:8000",
  chunkDurationMs: readNumber(import.meta.env.VITE_CHUNK_DURATION_MS as string | undefined, 30000),
  chunkOverlapMs: readNumber(import.meta.env.VITE_CHUNK_OVERLAP_MS as string | undefined, 5000),
  maxUploadRetries: readNumber(import.meta.env.VITE_MAX_UPLOAD_RETRIES as string | undefined, 5),
  uploadRetryBaseMs: readNumber(import.meta.env.VITE_UPLOAD_RETRY_BASE_MS as string | undefined, 1000),
  consentVersion: "v1.0",
} as const;
