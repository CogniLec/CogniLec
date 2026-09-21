// Central place for env-derived configuration (Vite convention: import.meta.env).

function readNumber(value: string | undefined, fallback: number): number {
  if (value === undefined || value === "") return fallback;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

export const CONFIG: {
  apiBaseUrl: string;
  chunkDurationMs: number;
  chunkOverlapMs: number;
  maxUploadRetries: number;
  uploadRetryBaseMs: number;
  consentVersion: string;
} = {
  apiBaseUrl: (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "http://localhost:8000",
  chunkDurationMs: readNumber(import.meta.env.VITE_CHUNK_DURATION_MS as string | undefined, 30000),
  chunkOverlapMs: readNumber(import.meta.env.VITE_CHUNK_OVERLAP_MS as string | undefined, 5000),
  maxUploadRetries: readNumber(import.meta.env.VITE_MAX_UPLOAD_RETRIES as string | undefined, 5),
  uploadRetryBaseMs: readNumber(import.meta.env.VITE_UPLOAD_RETRY_BASE_MS as string | undefined, 1000),
  consentVersion: "v1.0",
};

/**
 * Overrides the build-time API URL with `config.json` served next to the app.
 * The URL used to be baked into the bundle at build time, so every backend
 * address change (Funnel/tunnel rotation) meant a rebuild + redeploy, and
 * clients with a cached service worker kept calling the OLD address and saw
 * "Failed to fetch". config.json is fetched fresh (no-store, never precached
 * -- see vite.config.ts) so the address can change without touching the bundle.
 * Any failure silently keeps the build-time value.
 */
export async function loadRuntimeConfig(timeoutMs = 2500): Promise<void> {
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    const res = await fetch(`${import.meta.env.BASE_URL}config.json`, {
      cache: "no-store",
      signal: controller.signal,
    });
    clearTimeout(timer);
    if (!res.ok) return;
    const data = (await res.json()) as { apiBaseUrl?: unknown };
    if (typeof data.apiBaseUrl === "string" && data.apiBaseUrl.trim() !== "") {
      CONFIG.apiBaseUrl = data.apiBaseUrl.trim().replace(/\/+$/, "");
    }
  } catch {
    // keep build-time apiBaseUrl
  }
}
