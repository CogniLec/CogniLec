/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_CHUNK_DURATION_MS?: string;
  readonly VITE_CHUNK_OVERLAP_MS?: string;
  readonly VITE_MAX_UPLOAD_RETRIES?: string;
  readonly VITE_UPLOAD_RETRY_BASE_MS?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
