# BLOCK 2 — Capture & Ingestion
## Specification Document: S14–S20

**Implements:** SRS v1.0 · Architecture v1.0 · Stack Manifest v1.1 · FR-1.1, FR-1.3, FR-1.4, FR-1.5, FR-2.1, FR-2.2, FR-4.11, FR-6.3, FR-7.8, NFR-R1, NFR-R3, NFR-S4, NFR-S5, NFR-P1, NFR-P7, ADR-003, ADR-009, ADR-015, ADR-017, ADR-018
**Block Owner:** Backend + ML + Frontend
**Estimate:** 7 stages, ~2–3 weeks serial
**Gate:** ⛔ S20 — end-to-end ingestion spine must work on real audio before any downstream block begins

---

## Table of Contents

1. [Block Overview](#block-overview)
2. [S14 — Object Store Layout & Lifecycle Policies](#s14--object-store-layout--lifecycle-policies)
3. [S15 — Client Capture Application (PWA)](#s15--client-capture-application-pwa)
4. [S16 — Chunk Upload API & Stream Ingestion](#s16--chunk-upload-api--stream-ingestion)
5. [S17 — Audio Pre-Processing Chain](#s17--audio-pre-processing-chain)
6. [S18 — Audio Quality Metrics & Operator Warning](#s18--audio-quality-metrics--operator-warning)
7. [S19 — ASR Worker (Primary Model)](#s19--asr-worker-primary-model)
8. [S20 ⛔ — Anonymous Diarisation & Transcript Completion (GATE)](#s20--anonymous-diarisation--transcript-completion-gate)
9. [Cross-Stage Contracts](#cross-stage-contracts)
10. [Appendix A — Files Created by Block 2](#appendix-a--files-created-by-block-2)
11. [Appendix B — Config Keys Added](#appendix-b--config-keys-added)
12. [Appendix C — Observability Dashboard](#appendix-c--observability-dashboard)

---

## Block Overview

Block 2 is the **capture and ingestion spine**: audio goes in on a client device, flows through object storage, preprocessing, ASR, and diarisation, and emerges as a durable, word-timestamped, speaker-tagged transcript in DB-1. Every later block (B3–B13) builds on this output.

**Preconditions (must be true before Block 2 starts):**
- S06 gate passed: ASR and embedding models locked in `config/models.yaml`
- S03 compose stack running: MinIO (buckets provisioned), Valkey, PostgreSQL (schema from S07–S12)
- S07–S12 schema live: `sessions`, `subjects`, `utterances`, `segments` tables exist with correct DDL
- S13 test harness operational: testcontainers, synthetic transcript generator available

**What this block does NOT do:**
- Does not generate embeddings (S25–S26)
- Does not detect hallucinations or compute ASR agreement (S21–S22)
- Does not segment topics (S28–S30)
- Does not synthesize notes (S41–S46)

**Key architectural decisions invoked:**
- ADR-003: Valkey Streams for real-time chunk transport; consumer-group semantics
- ADR-009: Anonymous diarisation only — session-scoped `SPK_A` tags, zero biometric persistence
- ADR-015: 4GB VRAM constraint — model loading must be sequential, never concurrent
- ADR-017: 8-bit quantization where needed for larger models
- ADR-018: Local-first ASR — no hosted API dependency

---

## S14 — Object Store Layout & Lifecycle Policies

### 1. Stage Identity

| Field | Value |
|-------|-------|
| **ID** | S14 |
| **Name** | Object Store Layout & Lifecycle Policies |
| **Block** | B2 — Capture & Ingestion |
| **Owner** | Backend |
| **Estimate** | 1–2 days |
| **Deps** | S03 |
| **SRS** | NFR-S3, FR-4.11 |

### 2. Context

Block 2 requires durable, organised object storage for audio chunks, uploads, generated artefacts, exports, and evaluation data. S03 created the MinIO bucket provisioning script (`docker/minio/buckets.sh`), but no application-level storage client exists. This stage creates the storage client wrapper that all later stages use, adds presigned URL generation for direct client uploads (avoiding API proxy overhead for large audio files), and verifies that ILM lifecycle rules are correctly applied.

The bucket layout:
- `lis-audio`: raw audio chunks, ILM 30-day purge after session `complete`
- `lis-uploads`: temporary upload staging, permanent (manual cleanup)
- `lis-generated`: derived artefacts (reconstructed audio, alignment data), permanent
- `lis-exports`: final user-facing exports, ILM 7-day purge
- `lis-eval`: evaluation datasets, permanent, versioned with DVC

### 3. Dependencies

| Dependency | Type | Notes |
|------------|------|-------|
| S03 | Upstream stage | Compose stack with MinIO running; `docker/minio/buckets.sh` creates buckets |
| MinIO service | Infra | Running at `localhost:9000` (internal network), configured in `docker-compose.yml:181–212` |
| `minio` Python SDK | Library | Already in `pyproject.toml:27`: `minio>=7.2,<8.0` |
| `src/core/config.py` | Config | Already has `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `MINIO_BUCKET_*` |

### 4. Requirements Traced

| SRS ID | Requirement | How S14 implements |
|--------|-------------|---------------------|
| NFR-S3 | Data retention policies enforced automatically | ILM rules on `lis-audio` (30d) and `lis-exports` (7d) verified; policy-based, not cron-based |
| FR-4.11 | Object storage key scheme | Keys follow `{bucket}/{category}/{session_id}/{seq}.{ext}` pattern |

### 5. Interface Contracts

#### 5.1 Storage Client

```
File: src/ml/storage.py (CREATE)
```

```python
"""MinIO storage client with presigned URL generation."""
from __future__ import annotations

import uuid
from datetime import timedelta
from io import BytesIO

from minio import Minio
from minio.error import S3Error
import structlog

from src.core.config import get_settings

logger = structlog.get_logger()


class StorageClient:
    """Wrapper around MinIO providing typed bucket access and presigned URLs."""

    def __init__(self) -> None:
        settings = get_settings()
        self._client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )

    # --- Bucket helpers ---

    def bucket_audio(self) -> str:
        return get_settings().MINIO_BUCKET_AUDIO

    def bucket_uploads(self) -> str:
        return get_settings().MINIO_BUCKET_UPLOADS

    def bucket_generated(self) -> str:
        return get_settings().MINIO_BUCKET_GENERATED

    def bucket_exports(self) -> str:
        return get_settings().MINIO_BUCKET_EXPORTS

    # --- Upload ---

    def upload_chunk(
        self,
        session_id: uuid.UUID,
        seq: int,
        data: BytesIO,
        content_type: str = "audio/ogg",
    ) -> str:
        """Upload an audio chunk to lis-audio. Returns the object key."""
        key = f"audio/{session_id}/{seq:06d}.ogg"
        self._client.put_object(
            self.bucket_audio(),
            key,
            data,
            length=data.getbuffer().nbytes,
            content_type=content_type,
        )
        logger.info("chunk_uploaded", session_id=str(session_id), seq=seq, key=key)
        return key

    def get_chunk(self, session_id: uuid.UUID, seq: int) -> bytes:
        """Download an audio chunk from lis-audio."""
        key = f"audio/{session_id}/{seq:06d}.ogg"
        response = self._client.get_object(self.bucket_audio(), key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    # --- Presigned URLs ---

    def presigned_upload_url(
        self,
        session_id: uuid.UUID,
        seq: int,
        expiry: timedelta = timedelta(hours=1),
    ) -> str:
        """Generate a presigned PUT URL for direct client upload."""
        key = f"audio/{session_id}/{seq:06d}.ogg"
        url = self._client.presigned_put_object(
            self.bucket_audio(),
            key,
            expires=expiry,
        )
        logger.info(
            "presigned_url_generated",
            session_id=str(session_id),
            seq=seq,
            expires_seconds=int(expiry.total_seconds()),
        )
        return url

    # --- Lifecycle verification ---

    def get_ilm_rules(self, bucket: str) -> list[dict]:
        """Retrieve ILM lifecycle rules for a bucket."""
        # MinIO SDK lifecycle rule retrieval
        ...

    # --- Cleanup ---

    def delete_session_chunks(self, session_id: uuid.UUID) -> int:
        """Delete all chunks for a session (used in tests/rollback)."""
        prefix = f"audio/{session_id}/"
        objects = list(self._client.list_objects(self.bucket_audio(), prefix=prefix))
        for obj in objects:
            self._client.remove_object(self.bucket_audio(), obj.object_name)
        return len(objects)
```

#### 5.2 Presigned URL Endpoint

```
File: src/api/routes/sessions.py (MODIFY — add presigned URL endpoint)
```

```python
# Addition to existing router:

@router.post("/{session_id}/presigned-url")
async def get_presigned_upload_url(
    session_id: uuid.UUID,
    seq: int,
    db: AsyncSession = Depends(get_db_session),
) -> PresignedURLResponse:
    """Return a presigned PUT URL for direct chunk upload to MinIO."""
    repo = SessionRepository(db)
    session_obj = await repo.get_or_raise(session_id)
    if session_obj.status == SessionStatus.COMPLETE:
        raise HTTPException(status_code=409, detail="Session already complete")
    storage = StorageClient()
    url = storage.presigned_upload_url(session_id, seq)
    return PresignedURLResponse(url=url, key=f"audio/{session_id}/{seq:06d}.ogg")
```

#### 5.3 Pydantic Schemas

```
File: src/api/schemas/session.py (MODIFY — add PresignedURLResponse)
```

```python
class PresignedURLResponse(BaseModel):
    url: str
    key: str
```

#### 5.4 Key Scheme

```
lis-audio/audio/{session_id}/{seq:06d}.ogg     # raw audio chunks
lis-generated/audio/{session_id}/reassembled.wav  # reassembled audio for ASR
lis-generated/vad/{session_id}/{seq:06d}.npy     # VAD maps per chunk
lis-exports/notes/{session_id}/notes.md           # exported notes
lis-eval/phase0/v1/{session_id}/audio.opus        # S04 evaluation corpus
```

#### 5.5 SQL DDL

No new tables. S14 operates on existing infrastructure only.

### 6. Implementation Notes

**ILM Policy Verification:**
- `docker/minio/buckets.sh:36` already sets `--expire-days 30` on `lis-audio` with prefix filter `audio/`
- `docker/minio/buckets.sh:39` already sets `--expire-days 7` on `lis-exports`
- S14 tests verify these rules exist and are correctly expressed; no re-provisioning needed

**Presigned URL Scoping:**
- URLs are scoped to a single key (`audio/{session_id}/{seq:06d}.ogg`)
- Cannot write to a different key in the bucket (S3 bucket policy enforced)
- Default expiry: 1 hour (configurable via `PRESIGNED_URL_EXPIRY_MINUTES`)

**Failure Handling:**
- MinIO unavailable → `StorageClient.__init__` raises `ConnectionError`; API returns 503
- Presigned URL generation failure → HTTP 500 with structured error
- Upload failure on client → retry with same `seq` (idempotent; S16 handles dedup)

**Config Keys:**

```python
# src/core/config.py — additions to Settings class
PRESIGNED_URL_EXPIRY_MINUTES: int = 60
AUDIO_CHUNK_FORMAT: str = "ogg"
AUDIO_CHUNK_SAMPLE_RATE: int = 48000
```

### 7. Test Specification

| Test ID | Type | Given | When | Then |
|---------|------|-------|------|------|
| T14.1 | I | MinIO running with all 5 buckets provisioned; `StorageClient` instantiated | Upload an object to each bucket with the correct key scheme | Object exists at the expected key; can be read back byte-identically |
| T14.2 | I | MinIO running; `lis-audio` bucket with ILM rule from `buckets.sh` | Call `get_ilm_rules("lis-audio")` | Rule present with `expire_days=30` and prefix filter `audio/`; rule is "Enabled" |
| T14.3 | I | MinIO running; `StorageClient` instantiated | Generate a presigned PUT URL; use `httpx` to PUT a file; wait for expiry; attempt reuse | First upload succeeds (200); second upload with same URL fails (403 Forbidden) |
| T14.4 | S | MinIO running; presigned URL generated for key `audio/{sid}/000001.ogg` | Attempt PUT to key `audio/{sid}/../other.txt` using the presigned URL | PUT rejected — presigned URL is scoped to one key only |
| T14.5 | I | A session with chunks in `lis-audio`; ILM rule set to 1-day (test override) | Force lifecycle evaluation via `mc ilm rule ls` | Chunks older than 1 day expire; reassembled audio in `lis-generated` remains intact |

### 8. Observability

| Metric/Span | Type | Description |
|-------------|------|-------------|
| `lis_storage_chunk_upload_total` | Counter | Incremented per chunk upload; labels: `bucket`, `session_id` |
| `lis_storage_presigned_url_total` | Counter | Incremented per presigned URL generation |
| `lis_storage_ilm_rule_check` | Span | Traces ILM verification in tests |

### 9. Rollback

- **How to revert:** Delete the storage client code; no database migration to revert
- **Migration down-path:** N/A (no DDL changes)
- **Feature flag:** N/A (storage client is always-on infrastructure)

### 10. Exit Checklist

- [ ] All 5 buckets provisioned and accessible from application code
- [ ] ILM rules verified on `lis-audio` (30d) and `lis-exports` (7d)
- [ ] Presigned URL generation works; URLs expire correctly
- [ ] Presigned URL scoped to single key (security test passes)
- [ ] `StorageClient` imported and usable from future stages (S16, S17, S19)

---

## S15 — Client Capture Application (PWA)

### 1. Stage Identity

| Field | Value |
|-------|-------|
| **ID** | S15 |
| **Name** | Client Capture Application (PWA) |
| **Block** | B2 — Capture & Ingestion |
| **Owner** | Frontend |
| **Estimate** | 3–5 days |
| **Deps** | S03, S07 |
| **SRS** | FR-1.1, FR-1.4, NFR-R1, NFR-S5 |

### 2. Context

The LIS system needs a client-side application that runs on lecturer devices (phones, tablets, laptops) to capture lecture audio. The application must work reliably in real-world conditions: poor WiFi, backgrounding, tab switching, and even complete network loss. Audio must be captured in overlapping 30-second chunks for resilience (if a chunk is lost, only 30s is affected, not the whole lecture).

The PWA approach provides: installability on mobile devices, service worker for offline capability, and `getUserMedia` access in secure contexts (HTTPS via Traefik mkcert).

**Predecessors:** S03 (compose stack with HTTPS), S07 (subjects API for subject picker).

### 3. Dependencies

| Dependency | Type | Notes |
|------------|------|-------|
| S03 | Upstream | Traefik provides HTTPS; `getUserMedia` requires secure context |
| S07 | Upstream | `/subjects` API for subject picker; `SubjectResponse` schema |
| S16 | Downstream | Chunk upload endpoint `POST /sessions/{id}/chunks` |
| S14 | Downstream | Presigned URL endpoint for direct MinIO upload |
| React + Vite + Tailwind | Framework | No existing frontend code — must create from scratch |
| `opus-recorder` | Library | Web Audio API Opus encoder for browser recording |
| Workbox | Library | Service worker toolkit for offline IndexedDB ring buffer |
| `idb` | Library | IndexedDB wrapper for chunk buffering |

### 4. Requirements Traced

| SRS ID | Requirement | How S15 implements |
|--------|-------------|---------------------|
| FR-1.1 | Audio capture in lecture sessions | MediaRecorder + opus-recorder capturing 30s overlapping chunks |
| FR-1.4 | Chunked upload with resume | Upload queue with retry; IndexedDB ring buffer survives offline |
| NFR-R1 | Resilience to network loss | Chunks buffer to IndexedDB; upload resumes on reconnect |
| NFR-S5 | Consent before recording | Consent gate blocks recording start until acknowledged |

### 5. Interface Contracts

#### 5.1 Project Structure (CREATE)

```
frontend/
├── package.json
├── vite.config.ts
├── tsconfig.json
├── tailwind.config.js
├── postcss.config.js
├── public/
│   ├── manifest.json          # PWA manifest
│   ├── sw.js                  # Service worker (Workbox-generated)
│   └── icons/
│       ├── icon-192.png
│       └── icon-512.png
├── src/
│   ├── main.tsx               # React entry point
│   ├── App.tsx                # Root component with router
│   ├── index.css              # Tailwind base
│   ├── components/
│   │   ├── SubjectPicker.tsx  # Select subject before recording
│   │   ├── ConsentGate.tsx    # Consent acknowledgement modal
│   │   ├── RecordingView.tsx  # Active recording UI (timer, indicator, stop)
│   │   ├── UploadQueue.tsx    # Visual upload queue status
│   │   └── WarningBanner.tsx  # Audio quality warning display (S18)
│   ├── hooks/
│   │   ├── useRecorder.ts     # MediaRecorder + chunking logic
│   │   ├── useUploadQueue.ts  # IndexedDB-backed upload queue
│   │   └── useSSE.ts          # Server-Sent Events for status
│   ├── lib/
│   │   ├── db.ts              # IndexedDB schema (Workbox)
│   │   ├── api.ts             # API client (fetch wrapper)
│   │   ├── recorder.ts        # Opus recording + chunking
│   │   └── consent.ts         # Consent state management
│   ├── types/
│   │   └── index.ts           # TypeScript types
│   └── workers/
│       └── sw.ts              # Service worker source
```

#### 5.2 PWA Manifest

```json
{
  "name": "LIS Capture",
  "short_name": "LIS",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#0f172a",
  "theme_color": "#3b82f6",
  "icons": [
    { "src": "/icons/icon-192.png", "sizes": "192x192", "type": "image/png" },
    { "src": "/icons/icon-512.png", "sizes": "512x512", "type": "image/png" }
  ]
}
```

#### 5.3 Recording Hook Interface

```typescript
// src/hooks/useRecorder.ts

interface UseRecorderOptions {
  chunkDurationMs: number;     // 30000 (30s)
  overlapMs: number;           // 5000 (5s overlap)
  sampleRate: number;          // 48000
  channels: number;            // 1 (mono)
  onChunkReady: (chunk: Blob, seq: number) => Promise<void>;
}

interface UseRecorderReturn {
  isRecording: boolean;
  elapsed: number;             // seconds since start
  startRecording: () => Promise<void>;
  stopRecording: () => Promise<void>;
  error: string | null;
}

function useRecorder(options: UseRecorderOptions): UseRecorderReturn;
```

#### 5.4 Upload Queue Interface

```typescript
// src/hooks/useUploadQueue.ts

interface QueuedChunk {
  id: string;                  // UUID
  sessionId: string;
  seq: number;
  blob: Blob;
  status: 'pending' | 'uploading' | 'completed' | 'failed';
  retries: number;
  createdAt: number;           // timestamp
}

interface UseUploadQueueReturn {
  queue: QueuedChunk[];
  enqueue: (sessionId: string, seq: number, blob: Blob) => Promise<void>;
  processQueue: () => Promise<void>;
  pendingCount: number;
  failedCount: number;
}
```

#### 5.5 API Client

```typescript
// src/lib/api.ts

const API_BASE = import.meta.env.VITE_API_BASE || '/api';

export async function createSession(subjectId: string, sessionType?: string): Promise<Session>;
export async function getSession(sessionId: string): Promise<Session>;
export async function uploadChunk(sessionId: string, seq: number, blob: Blob): Promise<void>;
export async function completeSession(sessionId: string): Promise<void>;
export async function getPresignedUrl(sessionId: string, seq: number): Promise<{ url: string; key: string }>;
```

#### 5.6 IndexedDB Schema

```typescript
// src/lib/db.ts
// Object store: 'chunks'
// Key: auto-increment
// Indexes: sessionId+seq (unique), status

interface ChunkRecord {
  id?: number;
  sessionId: string;
  seq: number;
  blob: Blob;
  status: 'pending' | 'uploading' | 'completed' | 'failed';
  retries: number;
  createdAt: number;
}
```

### 6. Implementation Notes

**Chunking Strategy:**
- Record continuous audio via `MediaRecorder` (MIME: `audio/webm;codecs=opus`)
- Split into 30s chunks with 5s overlap (so consecutive chunks share 5s of audio)
- Overlap ensures no gap at chunk boundaries even if one chunk is delayed
- Each chunk uploaded as `audio/ogg` via presigned URL or direct upload

**Offline Resilience (NFR-R1):**
- Service worker caches app shell (HTML, CSS, JS) for instant load
- Audio chunks written to IndexedDB immediately on capture
- Upload queue processes chunks when network available
- `navigator.onLine` event triggers queue processing
- On reconnect: upload all pending chunks in sequence order

**Backgrounding (T15.3):**
- `MediaRecorder` continues recording when tab is backgrounded (browser-dependent)
- Service worker keeps upload alive via `Background Sync` API
- Fallback: periodic `setInterval` check to resume recording if browser paused it

**Consent Gate (T15.4):**
- Modal blocks recording start until user acknowledges consent text
- Consent text from `docs/consent-form.md` (loaded at build time or via API)
- Acknowledgement stored in `localStorage` (session-scoped, not persistent)
- Consent must be re-acknowledged per session

**Subject Picker (T15.5):**
- Fetches subjects from `GET /subjects` on app load
- Dropdown selector; recording cannot start without selection
- Selected subject passed to `POST /sessions` to create session

### 7. Test Specification

| Test ID | Type | Given | When | Then |
|---------|------|-------|------|------|
| T15.1 | E | PWA loaded in browser; mock MediaRecorder producing 30s chunks | Record for 60 minutes continuously | Expected chunk count = 120 (60min / 30s); each chunk has correct 5s overlap with neighbours |
| T15.2 | E | Recording in progress; network disconnected for 5 minutes | Chunks continue to be captured; network reconnects | All chunks buffered to IndexedDB during disconnect; all chunks upload successfully on reconnect; no data loss |
| T15.3 | E | Recording in progress; tab backgrounded for 2 minutes, then foregrounded | Recording continues across background/foreground cycle | No chunk gap; `elapsed` timer continuous; chunk sequence unbroken |
| T15.4 | U | PWA loaded; consent not yet acknowledged | Attempt to start recording | Recording blocked; consent modal displayed; `startRecording` throws until consent given |
| T15.5 | U | PWA loaded; no subject selected | Attempt to start recording | Recording blocked; subject picker highlighted; session not created |
| T15.6 | E | Recording in progress; browser tab closed abruptly | Reopen the PWA | Buffered chunks in IndexedDB detected; upload resumes and completes |
| T15.7 | P | 60-minute recording session completed | Export Opus-encoded audio from chunks | Total file size ≤ 15MB (Opus at ~32kbps for mono 48kHz) |

### 8. Observability

| Metric/Span | Type | Description |
|-------------|------|-------------|
| `lis_capture_recording_started` | Event | Emitted when recording begins; labels: `subject_id`, `session_id` |
| `lis_capture_chunk_buffered` | Counter | Incremented per chunk written to IndexedDB |
| `lis_capture_chunk_uploaded` | Counter | Incremented per successful chunk upload |
| `lis_capture_chunk_failed` | Counter | Incremented per failed upload attempt |
| `lis_capture_network_disconnected` | Event | Emitted on network loss detection |
| `lis_capture_network_reconnected` | Event | Emitted on reconnect; payload includes `chunks_pending` |

### 9. Rollback

- **How to revert:** Remove `frontend/` directory; no backend changes to revert
- **Migration down-path:** N/A (no DDL changes)
- **Feature flag:** PWA is client-side only; removing it does not affect backend

### 10. Exit Checklist

- [ ] PWA installs on Android Chrome and iOS Safari
- [ ] 60-minute recording produces correct chunk count with overlap
- [ ] Network disconnect → IndexedDB buffer → reconnect → upload completes
- [ ] Background/foreground cycle produces no chunk gap
- [ ] Consent gate blocks recording until acknowledged
- [ ] Subject picker blocks recording until selection made
- [ ] Browser tab close → chunks upload on next app open
- [ ] Opus output ≤ 15MB for 60 minutes

---

## S16 — Chunk Upload API & Stream Ingestion

### 1. Stage Identity

| Field | Value |
|-------|-------|
| **ID** | S16 |
| **Name** | Chunk Upload API & Stream Ingestion |
| **Block** | B2 — Capture & Ingestion |
| **Owner** | Backend |
| **Estimate** | 2–3 days |
| **Deps** | S14, S15 |
| **SRS** | FR-1.1, FR-1.4 |

### 2. Context

The PWA (S15) captures audio chunks and needs to send them to the server. This stage creates the `POST /sessions/{id}/chunks` endpoint that accepts chunk uploads, writes them to object storage, and publishes messages to a Valkey Stream for downstream consumers (S17 preprocessing, S19 ASR). The endpoint must be idempotent on `(session_id, seq)` so client retries are safe.

Additionally, an SSE endpoint streams session status transitions to the client, so the PWA can display recording state and respond to quality warnings (S18).

The session state machine transitions from `created → recording` on the first chunk upload.

**Predecessors:** S14 (storage client for MinIO writes), S15 (PWA producing chunks).

### 3. Dependencies

| Dependency | Type | Notes |
|------------|------|-------|
| S14 | Upstream | `StorageClient` for writing chunks to `lis-audio` |
| S15 | Upstream | PWA producing chunks; client upload logic |
| S07 | Schema | `Session.status` enum; `SessionStatus.CREATED` and `.RECORDING` |
| Valkey service | Infra | Running at `localhost:6379` (internal network), `docker-compose.yml:149–176` |
| `redis` Python SDK | Library | Already in `pyproject.toml:24`: `redis>=5.1,<6.0` |

### 4. Requirements Traced

| SRS ID | Requirement | How S16 implements |
|--------|-------------|---------------------|
| FR-1.1 | Chunk upload | `POST /sessions/{id}/chunks` accepts chunk + metadata |
| FR-1.4 | Idempotent upload | `(session_id, seq)` unique constraint; duplicate accepted, not double-published |
| NFR-P7 | 20 concurrent sessions sustained | Valkey Stream consumer groups handle parallel ingestion |

### 5. Interface Contracts

#### 5.1 API Endpoints

```
File: src/api/routes/sessions.py (MODIFY — add chunk upload + SSE endpoints)
```

**POST /sessions/{session_id}/chunks**

Request:
```http
POST /api/v1/sessions/{session_id}/chunks
Content-Type: multipart/form-data

seq: 0
timestamp_ms: 1726108800000
chunk: <binary audio data>
```

Response (201 Created):
```json
{
  "status": "accepted",
  "seq": 0,
  "session_status": "recording"
}
```

Error responses:
- `404` — session not found
- `409` — session already complete
- `422` — missing `seq` or `chunk`

**GET /sessions/{session_id}/events** (SSE)

```http
GET /api/v1/sessions/{session_id}/events
Accept: text/event-stream
```

Events:
```
event: status
data: {"status": "recording", "timestamp": "2026-09-12T10:00:00Z"}

event: quality_warning
data: {"snr_db": 12.3, "speech_ratio": 0.15, "message": "Audio quality degraded"}

event: complete
data: {"status": "transcribed", "timestamp": "2026-09-12T11:05:00Z"}
```

#### 5.2 Pydantic Schemas

```
File: src/api/schemas/session.py (MODIFY)
```

```python
class ChunkUploadResponse(BaseModel):
    status: str  # "accepted"
    seq: int
    session_status: SessionStatus

class SessionEvent(BaseModel):
    event: str  # "status", "quality_warning", "complete"
    data: dict[str, Any]
    timestamp: datetime
```

#### 5.3 Valkey Stream

Stream name: `audio.chunk`

Message format:
```json
{
  "session_id": "uuid",
  "subject_id": "uuid",
  "seq": 0,
  "timestamp_ms": 1726108800000,
  "object_key": "audio/{session_id}/000000.ogg",
  "uploaded_at": "2026-09-12T10:00:05Z"
}
```

Consumer group: `preprocessing` (S17 consumer)
- Group name: `preprocessing`
- Consumer name: `worker-{pid}` (auto-assigned)

#### 5.4 Stream Producer

```
File: src/core/streams.py (CREATE)
```

```python
"""Valkey Stream producer for audio chunk events."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import redis.asyncio as redis
import structlog

from src.core.config import get_settings

logger = structlog.get_logger()

STREAM_NAME = "audio.chunk"
CONSUMER_GROUP = "preprocessing"


class StreamProducer:
    def __init__(self) -> None:
        self._redis = redis.from_url(get_settings().VALKEY_URL, decode_responses=True)

    async def publish_chunk(
        self,
        session_id: uuid.UUID,
        subject_id: uuid.UUID,
        seq: int,
        timestamp_ms: int,
        object_key: str,
    ) -> str:
        """Publish a chunk event to the audio.chunk stream. Returns message ID."""
        message = {
            "session_id": str(session_id),
            "subject_id": str(subject_id),
            "seq": str(seq),
            "timestamp_ms": str(timestamp_ms),
            "object_key": object_key,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
        }
        msg_id = await self._redis.xadd(STREAM_NAME, message)
        logger.info(
            "chunk_published",
            session_id=str(session_id),
            seq=seq,
            stream_msg_id=msg_id,
        )
        return msg_id

    async def ensure_consumer_group(self) -> None:
        """Create consumer group if it doesn't exist."""
        try:
            await self._redis.xgroup_create(STREAM_NAME, CONSUMER_GROUP, id="0", mkstream=True)
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise
```

#### 5.5 SSE Manager

```
File: src/core/sse.py (CREATE)
```

```python
"""Server-Sent Events manager for session status streaming."""
from __future__ import annotations

import asyncio
import json
import uuid
from collections import defaultdict

import structlog

logger = structlog.get_logger()


class SSEManager:
    """Manages per-session SSE connections."""

    def __init__(self) -> None:
        self._queues: dict[uuid.UUID, list[asyncio.Queue]] = defaultdict(list)

    def subscribe(self, session_id: uuid.UUID) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._queues[session_id].append(queue)
        return queue

    def unsubscribe(self, session_id: uuid.UUID, queue: asyncio.Queue) -> None:
        self._queues[session_id].remove(queue)

    async def emit(self, session_id: uuid.UUID, event: str, data: dict) -> None:
        """Emit an event to all subscribers of a session."""
        payload = json.dumps({"event": event, "data": data})
        for queue in self._queues.get(session_id, []):
            await queue.put(payload)

    async def event_stream(self, session_id: uuid.UUID):
        """Yield SSE-formatted events for a session."""
        queue = self.subscribe(session_id)
        try:
            while True:
                data = await queue.get()
                yield f"data: {data}\n\n"
        finally:
            self.unsubscribe(session_id, queue)


# Global singleton
sse_manager = SSEManager()
```

#### 5.6 Idempotency Layer

```
File: src/core/idempotency.py (CREATE)
```

```python
"""Idempotency check for chunk uploads using Valkey SET NX."""
from __future__ import annotations

import uuid

import redis.asyncio as redis

from src.core.config import get_settings


class ChunkIdempotencyCheck:
    """Check if a chunk (session_id, seq) has already been processed."""

    def __init__(self) -> None:
        self._redis = redis.from_url(get_settings().VALKEY_URL, decode_responses=True)

    async def is_duplicate(self, session_id: uuid.UUID, seq: int) -> bool:
        """Return True if this chunk was already uploaded. Uses SET NX for atomicity."""
        key = f"chunk:{session_id}:{seq}"
        result = await self._redis.set(key, "1", nx=True, ex=86400)  # 24h TTL
        return result is None  # None means key already existed

    async def mark_uploaded(self, session_id: uuid.UUID, seq: int) -> None:
        """Mark a chunk as uploaded (called after successful stream publish)."""
        key = f"chunk:{session_id}:{seq}"
        await self._redis.set(key, "1", ex=86400)
```

### 6. Implementation Notes

**Idempotency (T16.2):**
- `ChunkIdempotencyCheck` uses Valkey `SET NX` (atomic set-if-not-exists) with 24h TTL
- If `is_duplicate()` returns `True`, the endpoint returns 200 (not 201) and skips stream publish
- This ensures client retries are safe: same `(session, seq)` accepted but not double-published

**Session State Transition (T16.6):**
- First chunk upload transitions `created → recording`
- Subsequent chunks: no state change (already `recording`)
- Chunk upload rejected with 409 if session status is `complete` or `failed`
- State transition uses `SessionRepository.update_status()` (exists at `src/db/repositories/session_repo.py:53`)

**SSE Stream Ordering (T16.5):**
- Events emitted in order: `created → recording → quality_warning* → transcribed`
- SSE connection kept alive via `X-Accel-Buffering: no` header
- Client reconnects with `Last-Event-ID` header for resumption

**Concurrent Sessions (T16.4):**
- Valkey Stream consumer groups handle 20+ concurrent sessions
- Each session's chunks are independent; no cross-session locking
- Consumer group ensures each message processed exactly once

**Failure Handling:**
- MinIO write failure → HTTP 503, chunk not published to stream
- Valkey Stream failure → chunk stored in MinIO but not published; retry via background task
- Session not found → HTTP 404
- Session already complete → HTTP 409

### 7. Test Specification

| Test ID | Type | Given | When | Then |
|---------|------|-------|------|------|
| T16.1 | I | Session in `created` status; MinIO and Valkey running | POST chunk with `seq=0` | Chunk stored in MinIO at `audio/{session_id}/000000.ogg`; message present on `audio.chunk` stream; session status transitions to `recording` |
| T16.2 | I | Session in `recording` status; chunk with `seq=0` already uploaded | POST chunk with `seq=0` again (retry) | Response 200 (not 201); chunk NOT double-published to stream; MinIO object overwritten (idempotent) |
| T16.3 | I | Session in `recording` status; chunks 0, 1, 2 uploaded | POST chunk with `seq=5` (out of order) | Chunk accepted and stored with correct `seq=5`; stream message has `seq=5` |
| T16.4 | P | 20 sessions in `recording` status; each uploading chunks every 30s | Sustain for 10 minutes | No backlog growth in Valkey Stream; all chunks processed within 5s of upload |
| T16.5 | I | Session in `recording` status; SSE client connected | Complete session (trigger `transcribed` status) | SSE stream emits `status` event with `transcribed` in order; no missed events |
| T16.6 | I | Session in `complete` status | POST chunk | HTTP 409; chunk rejected; no write to MinIO or stream |

### 8. Observability

| Metric/Span | Type | Description |
|-------------|------|-------------|
| `lis_chunk_upload_total` | Counter | Incremented per chunk upload; labels: `status` (accepted/rejected/duplicate) |
| `lis_chunk_upload_latency_ms` | Histogram | Time from POST start to response; labels: `session_status` |
| `lis_stream_publish_total` | Counter | Incremented per stream message; labels: `session_id` |
| `lis_stream_publish_latency_ms` | Histogram | Time from chunk received to stream message published |
| `lis_sse_connections_active` | Gauge | Current SSE connections; labels: `session_id` |
| `lis_session_state_transition` | Counter | Incremented per state transition; labels: `from`, `to` |

### 9. Rollback

- **How to revert:** Remove chunk upload and SSE endpoints from `src/api/routes/sessions.py`; remove `src/core/streams.py`, `src/core/sse.py`, `src/core/idempotency.py`
- **Migration down-path:** N/A (no DDL changes)
- **Feature flag:** N/A (chunk upload is core functionality)

### 10. Exit Checklist

- [ ] `POST /sessions/{id}/chunks` accepts chunk and metadata
- [ ] Chunk stored in MinIO with correct key scheme
- [ ] Stream message published to `audio.chunk`
- [ ] Duplicate `(session, seq)` accepted but not double-published
- [ ] Out-of-order chunks stored correctly by sequence
- [ ] SSE stream emits status transitions in order
- [ ] 20 concurrent sessions sustained without backlog
- [ ] Session `complete` rejects further chunks

---

## S17 — Audio Pre-Processing Chain

### 1. Stage Identity

| Field | Value |
|-------|-------|
| **ID** | S17 |
| **Name** | Audio Pre-Processing Chain |
| **Block** | B2 — Capture & Ingestion |
| **Owner** | ML |
| **Estimate** | 2–3 days |
| **Deps** | S16, S02 |
| **SRS** | FR-1.3, SR-01 mitigation, v1.1 §11 |

### 2. Context

Raw audio from lecture capture contains noise, varying volume levels, and long silences. Passing this directly to the ASR model (S19) degrades quality and triggers Whisper hallucination on silent regions. This stage implements a fixed preprocessing chain: ffmpeg normalisation → DeepFilterNet denoising → Silero VAD speech detection.

The VAD map is the **primary structural mitigation for Whisper hallucination** — silence never reaches the ASR model. This is explicitly called out in SR-01 and v1.1 §11 as the most important anti-hallucination measure.

**Predecessors:** S16 (chunk upload producing `audio.chunk` stream events), S02 (GPU host with ffmpeg, DeepFilterNet).

### 3. Dependencies

| Dependency | Type | Notes |
|------------|------|-------|
| S16 | Upstream | `audio.chunk` Valkey Stream; consumer group `preprocessing` |
| S02 | GPU host | ffmpeg, DeepFilterNet, Silero VAD installed on GPU container |
| `faster-whisper` | Library | For forced alignment (word timestamps); already in `pyproject.toml:71` |
| `torch` | Library | For Silero VAD model; already in `pyproject.toml:75` |
| `pydub` | Library | Audio manipulation; already in `pyproject.toml:87` |
| Valkey | Infra | Stream consumer; `docker-compose.yml:149` |
| MinIO | Infra | Reads chunks from `lis-audio`, writes processed audio to `lis-generated` |

### 4. Requirements Traced

| SRS ID | Requirement | How S17 implements |
|--------|-------------|---------------------|
| FR-1.3 | Audio preprocessing | ffmpeg loudnorm + DeepFilterNet denoise + Silero VAD |
| SR-01 | Hallucination mitigation | VAD drops speechless regions before ASR — silence never reaches model |
| v1.1 §11 | Preprocessing chain | Fixed chain: normalise → denoise → VAD; output is 16kHz mono |

### 5. Interface Contracts

#### 5.1 Worker

```
File: src/workers/preprocessing_worker.py (CREATE)
```

```python
"""Audio preprocessing worker — consumes audio.chunk, produces processed audio + VAD map."""
from __future__ import annotations

import asyncio
import json
import tempfile
import uuid
from pathlib import Path

import numpy as np
import structlog
from pydub import AudioSegment

from src.core.config import get_settings
from src.core.streams import STREAM_NAME, CONSUMER_GROUP
from src.ml.preprocessing.chain import PreprocessingChain

logger = structlog.get_logger()


class PreprocessingWorker:
    """Consumes chunks from audio.chunk stream, runs preprocessing chain."""

    def __init__(self, worker_id: str | None = None) -> None:
        self._worker_id = worker_id or f"preprocessing-{__import__('os').getpid()}"
        self._chain = PreprocessingChain()
        self._storage = None  # StorageClient from S14

    async def run(self) -> None:
        """Main loop: consume from stream, process, publish."""
        # Ensure consumer group exists
        # Loop: read from stream, process each chunk, ack
        ...

    async def process_chunk(
        self,
        session_id: uuid.UUID,
        subject_id: uuid.UUID,
        seq: int,
        object_key: str,
    ) -> PreprocessingResult:
        """
        1. Download chunk from MinIO (lis-audio)
        2. Run preprocessing chain:
           a. ffmpeg: 16kHz mono, EBU R128 loudnorm
           b. DeepFilterNet: denoise
           c. Silero VAD: detect speech regions
        3. Upload processed audio to lis-generated
        4. Upload VAD map to lis-generated
        5. Return result with speech regions
        """
        ...
```

#### 5.2 Preprocessing Chain

```
File: src/ml/preprocessing/chain.py (CREATE)
```

```python
"""Fixed preprocessing chain: ffmpeg → DeepFilterNet → Silero VAD."""
from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import structlog

logger = structlog.get_logger()


@dataclass
class VADRegion:
    start_ms: int
    end_ms: int
    probability: float


@dataclass
class PreprocessingResult:
    processed_audio_path: Path
    vad_regions: list[VADRegion]
    speech_ratio: float        # fraction of audio containing speech
    duration_ms: int
    sample_rate: int           # always 16000


class PreprocessingChain:
    """Fixed chain: ffmpeg loudnorm → DeepFilterNet denoise → Silero VAD."""

    TARGET_SAMPLE_RATE = 16000
    TARGET_CHANNELS = 1        # mono
    TARGET_LUFS = -23.0        # EBU R128 target

    def process(self, input_path: Path) -> PreprocessingResult:
        """
        Run the full preprocessing chain on an audio file.
        Returns processed audio path and VAD regions.
        """
        # Step 1: ffmpeg loudnorm (16kHz mono, EBU R128)
        normalised = self._normalise(input_path)

        # Step 2: DeepFilterNet denoise
        denoised = self._denoise(normalised)

        # Step 3: Silero VAD
        vad_regions = self._detect_speech(denoised)

        # Step 4: Strip silence (keep only speech regions + padding)
        processed = self._strip_silence(denoised, vad_regions)

        return PreprocessingResult(
            processed_audio_path=processed,
            vad_regions=vad_regions,
            speech_ratio=self._compute_speech_ratio(vad_regions, self._get_duration_ms(processed)),
            duration_ms=self._get_duration_ms(processed),
            sample_rate=self.TARGET_SAMPLE_RATE,
        )

    def _normalise(self, input_path: Path) -> Path:
        """ffmpeg: convert to 16kHz mono WAV with EBU R128 loudnorm."""
        output = Path(tempfile.mktemp(suffix=".wav"))
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(input_path),
                "-ar", str(self.TARGET_SAMPLE_RATE),
                "-ac", str(self.TARGET_CHANNELS),
                "-af", f"loudnorm=I={self.TARGET_LUFS}:TP=-1:LRA=11",
                str(output),
            ],
            capture_output=True,
            check=True,
        )
        return output

    def _denoise(self, audio_path: Path) -> Path:
        """DeepFilterNet: apply noise reduction."""
        # DeepFilterNet inference
        ...

    def _detect_speech(self, audio_path: Path) -> list[VADRegion]:
        """Silero VAD: detect speech regions with timestamps."""
        # Load Silero VAD model
        # Process audio in chunks
        # Return list of VADRegion with start_ms, end_ms, probability
        ...

    def _strip_silence(self, audio_path: Path, regions: list[VADRegion]) -> Path:
        """Keep only speech regions with small padding."""
        ...

    def _compute_speech_ratio(self, regions: list[VADRegion], total_ms: int) -> float:
        if total_ms == 0:
            return 0.0
        speech_ms = sum(r.end_ms - r.start_ms for r in regions)
        return speech_ms / total_ms

    def _get_duration_ms(self, audio_path: Path) -> int:
        ...
```

#### 5.3 Config Keys

```python
# src/core/config.py — additions to Settings class
PREPROCESSING_SAMPLE_RATE: int = 16000
PREPROCESSING_TARGET_LUFS: float = -23.0
VAD_THRESHOLD: float = 0.5           # Silero VAD confidence threshold
VAD_MIN_SPEECH_MS: int = 250         # minimum speech segment duration
VAD_SPEECH_PADDING_MS: int = 300     # padding around speech regions
DEEPFILTERNET_ENABLED: bool = True
PREPROCESSING_WORKER_CONCURRENCY: int = 1  # sequential on 4GB VRAM
```

### 6. Implementation Notes

**Critical Anti-Hallucination Measure (SR-01):**
- The VAD map is the **primary structural mitigation** for Whisper hallucination
- Silence and steady noise are removed before ASR; the model never sees speechless regions
- This is not optional — it is the most important quality measure in the pipeline

**GPU Memory (4GB VRAM):**
- Preprocessing runs on CPU (ffmpeg, DeepFilterNet, Silero VAD are CPU-friendly)
- ASR model (S19) runs on GPU; preprocessing must complete before ASR starts
- `PREPROCESSING_WORKER_CONCURRENCY=1` on 4GB VRAM (sequential processing)

**Failure Handling:**
- ffmpeg failure → chunk marked as failed; logged; not published to next stream
- DeepFilterNet failure → fall through to denoised=None (use normalised only)
- Silero VAD failure → `vad_regions=[]` (empty); downstream ASR processes full audio (with hallucination risk)
- Never crash the worker on a single chunk failure; skip and continue

### 7. Test Specification

| Test ID | Type | Given | When | Then |
|---------|------|-------|------|------|
| T17.1 | U | Audio file at 44.1kHz stereo MP3 | Run preprocessing chain | Output is 16kHz mono WAV regardless of input format/rate |
| T17.2 | V | Audio file with LUFS = -35 (deliberately quiet) | Run preprocessing chain | Output LUFS within -25 to -20 range (EBU R128 target met) |
| T17.3 | V | Audio file containing 30s of pure digital silence | Run Silero VAD on preprocessed output | VAD regions list is empty; speech_ratio = 0.0 |
| T17.4 | V | Audio file containing 30s of HVAC-only noise (no speech) | Run full preprocessing chain | DeepFilterNet reduces noise; VAD regions list is empty |
| T17.5 | V | Audio file with quiet speech (-30dB) + background noise | Run full preprocessing chain | Speech regions detected; speech not gated out; speech_ratio > 0.0 |
| T17.6 | V | Audio file with known SNR from S04 corpus | Run DeepFilterNet denoise | SNR improved by ≥ 3dB on output |
| T17.7 | P | 30s audio chunk on GPU host | Run full preprocessing chain | Chain completes in < 3s (real-time factor < 1) |

### 8. Observability

| Metric/Span | Type | Description |
|-------------|------|-------------|
| `lis_preprocessing_chunk_total` | Counter | Incremented per chunk processed; labels: `status` (success/failed) |
| `lis_preprocessing_duration_ms` | Histogram | Per-chunk preprocessing time; labels: `step` (normalise/denoise/vad) |
| `lis_preprocessing_speech_ratio` | Histogram | Speech ratio distribution; labels: `session_id` |
| `lis_preprocessing_vad_regions` | Histogram | Number of VAD regions per chunk |
| `lis_preprocessing_step_latency_ms` | Histogram | Per-step latency; labels: `step` (ffmpeg/deepfilternet/vad) |

### 9. Rollback

- **How to revert:** Disable `DEEPFILTERNET_ENABLED` and `VAD_THRESHOLD=0.0` to skip denoising and VAD; audio passes through with loudnorm only
- **Migration down-path:** N/A (no DDL changes)
- **Feature flag:**

```python
PREPROCESSING_ENABLED: bool = True  # set False to skip entire chain
DEEPFILTERNET_ENABLED: bool = True  # set False to skip denoising only
VAD_ENABLED: bool = True            # set False to skip VAD (NOT RECOMMENDED — hallucination risk)
```

### 10. Exit Checklist

- [ ] Output is 16kHz mono regardless of input format
- [ ] Loudnorm brings quiet audio within target LUFS
- [ ] Pure silence produces zero speech regions
- [ ] HVAC-only noise produces zero speech regions
- [ ] Quiet real speech is preserved (not gated out)
- [ ] DeepFilterNet improves SNR on noisy samples
- [ ] Chain processes 30s chunk in < 3s

---

## S18 — Audio Quality Metrics & Operator Warning

### 1. Stage Identity

| Field | Value |
|-------|-------|
| **ID** | S18 |
| **Name** | Audio Quality Metrics & Operator Warning |
| **Block** | B2 — Capture & Ingestion |
| **Owner** | Backend + Frontend |
| **Estimate** | 1–2 days |
| **Deps** | S17 |
| **SRS** | FR-1.5 |

### 2. Context

A lecturer may start recording with the phone in a pocket, facing away from the speaker, or in a noisy environment. Without real-time feedback, the entire session may be unusable. This stage computes per-chunk audio quality metrics (SNR, VAD speech ratio, clipping rate), aggregates them to a session `audio_quality` score, and emits warnings over SSE when quality drops below a configurable threshold. The PWA (S15) displays the warning so the operator can reposition the device during the lecture.

**Predecessors:** S17 (preprocessing chain produces VAD map and processed audio).

### 3. Dependencies

| Dependency | Type | Notes |
|------------|------|-------|
| S17 | Upstream | Preprocessing chain output: processed audio, VAD regions, speech_ratio |
| S16 | Infra | SSE manager (`src/core/sse.py`) for emitting warnings to client |
| S15 | Frontend | `WarningBanner.tsx` component for displaying warnings |
| `sessions.audio_quality` | Schema | Column exists from S07 migration (`a6f03a872c52`), currently NULL |

### 4. Requirements Traced

| SRS ID | Requirement | How S18 implements |
|--------|-------------|---------------------|
| FR-1.5 | Audio quality monitoring | Per-chunk SNR, speech ratio, clipping rate; session aggregate; SSE warnings |

### 5. Interface Contracts

#### 5.1 Quality Metrics Computation

```
File: src/ml/preprocessing/quality.py (CREATE)
```

```python
"""Audio quality metrics computation."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class ChunkQualityMetrics:
    snr_db: float              # signal-to-noise ratio in dB
    speech_ratio: float        # fraction of audio containing speech (from VAD)
    clipping_rate: float       # fraction of samples at max amplitude
    rms_level_db: float        # RMS level in dBFS


@dataclass
class SessionQualityScore:
    mean_snr_db: float
    min_snr_db: float
    mean_speech_ratio: float
    clipping_rate: float       # overall clipping
    score: float               # composite score [0.0, 1.0]
    is_warning: bool           # True if below threshold


def compute_chunk_metrics(
    audio: np.ndarray,
    sample_rate: int,
    vad_regions: list,
) -> ChunkQualityMetrics:
    """Compute quality metrics for a single chunk."""
    # SNR: estimate from speech vs non-speech regions
    # Speech ratio: from VAD regions
    # Clipping rate: samples at ±max amplitude
    # RMS level: root mean square in dBFS
    ...


def compute_session_score(
    chunk_metrics: list[ChunkQualityMetrics],
    snr_threshold_db: float = 15.0,
    speech_ratio_threshold: float = 0.1,
) -> SessionQualityScore:
    """Aggregate chunk metrics to session quality score."""
    # Score = weighted combination of SNR, speech ratio, clipping
    # Warning triggered if score < threshold
    ...
```

#### 5.2 SSE Warning Events

```json
{
  "event": "quality_warning",
  "data": {
    "snr_db": 12.3,
    "speech_ratio": 0.15,
    "clipping_rate": 0.02,
    "message": "Audio quality degraded — consider repositioning the device",
    "threshold_breached": "snr"
  }
}
```

#### 5.3 Config Keys

```python
# src/core/config.py — additions to Settings class
QUALITY_SNR_WARNING_THRESHOLD_DB: float = 15.0
QUALITY_SPEECH_RATIO_WARNING_THRESHOLD: float = 0.1
QUALITY_CLIPPING_WARNING_THRESHOLD: float = 0.05
QUALITY_ROLLING_WINDOW_SIZE: int = 5  # chunks to average for warning
QUALITY_WARNING_COOLDOWN_SECONDS: int = 60  # minimum time between warnings
```

### 6. Implementation Notes

**Rolling Window Warning:**
- Warning emitted when rolling window of last N chunks falls below threshold
- Cooldown prevents warning spam (minimum 60s between warnings)
- Warning appears in PWA within 10s of onset (T18.3)

**Session Quality Score:**
- Computed as weighted average: `score = 0.4 * snr_norm + 0.3 * speech_ratio + 0.3 * (1 - clipping_rate)`
- `snr_norm = min(1.0, snr_db / 30.0)` (normalised to [0, 1])
- Persisted to `sessions.audio_quality` on session completion

**Failure Handling:**
- Metrics computation failure → `audio_quality = NULL` (not 0.0); warning not emitted
- SSE emit failure → warning logged but not blocking
- Never block ASR on quality metric failure

### 7. Test Specification

| Test ID | Type | Given | When | Then |
|---------|------|-------|------|------|
| T18.1 | U | Audio fixture with known SNR = 20dB, speech_ratio = 0.8, clipping = 0.01 | Compute chunk metrics | `snr_db ≈ 20`, `speech_ratio ≈ 0.8`, `clipping_rate ≈ 0.01` |
| T18.2 | I | Session with 3 chunks; rolling window threshold set to SNR < 15dB | Process 3 chunks with SNR = 10dB each | Warning event emitted on SSE; event contains `snr_db`, `message`, `threshold_breached` |
| T18.3 | I | PWA connected via SSE; audio quality degrades during recording | Warning emitted by backend | Warning banner appears in client UI within 10s of onset |
| T18.4 | I | Session with 10 processed chunks | Session completes | `sessions.audio_quality` persisted as float in [0.0, 1.0]; matches `compute_session_score()` output |
| T18.5 | U | Config with `QUALITY_SNR_WARNING_THRESHOLD_DB = 10.0` | Change threshold to 20.0; process chunk with SNR = 15dB | Warning emitted at threshold=20 but not at threshold=10; configurable without code change |

### 8. Observability

| Metric/Span | Type | Description |
|-------------|------|-------------|
| `lis_quality_chunk_metrics` | Gauge | Per-chunk metrics; labels: `session_id`, `metric` (snr/clipping/speech_ratio) |
| `lis_quality_warning_emitted` | Counter | Incremented per warning emission; labels: `threshold_breached` |
| `lis_quality_session_score` | Gauge | Session quality score on completion |

### 9. Rollback

- **How to revert:** Disable quality metrics by setting all thresholds to 0.0
- **Migration down-path:** N/A (no DDL changes; `audio_quality` column already exists)
- **Feature flag:**

```python
QUALITY_MONITORING_ENABLED: bool = True  # set False to disable all quality checks
```

### 10. Exit Checklist

- [ ] Per-chunk metrics (SNR, speech ratio, clipping) computed correctly
- [ ] Sub-threshold audio triggers SSE warning
- [ ] Warning appears in client UI within 10s
- [ ] Session `audio_quality` persisted on completion
- [ ] Threshold configurable without code change

---

## S19 — ASR Worker (Primary Model)

### 1. Stage Identity

| Field | Value |
|-------|-------|
| **ID** | S19 |
| **Name** | ASR Worker (Primary Model) |
| **Block** | B2 — Capture & Ingestion |
| **Owner** | ML |
| **Estimate** | 3–5 days |
| **Deps** | S17, S06, S09 |
| **SRS** | FR-2.1, FR-2.2, FR-7.8, ADR-015, ADR-017, ADR-018 |

### 2. Context

This is the core ASR stage: processed audio chunks are transcribed into word-level-timestamped utterances and persisted to the `utterances` table. The model is `whisper-large-v3-turbo` (locked at S06, `config/models.yaml`) running via `faster-whisper` (CTranslate2 backend) with wav2vec2 forced alignment for word-level timestamps (required by provenance in later stages).

**NFR-R3 durability gate:** The transcript must be committed to DB-1 before any downstream stage (S20 diarisation, Block 3+) is permitted to start. This is the most critical correctness constraint in the pipeline.

Session state transitions `recording → transcribed` on completion.

**Predecessors:** S17 (preprocessed audio with VAD map), S06 (model lock), S09 (utterances table schema).

### 3. Dependencies

| Dependency | Type | Notes |
|------------|------|-------|
| S17 | Upstream | Preprocessed audio (16kHz mono WAV) + VAD regions |
| S06 | Model lock | `whisper-large-v3-turbo`, `faster-whisper`, CTranslate2 |
| S09 | Schema | `utterances` table with `subject_id`, `session_id`, `seq`, `start_ms`, `end_ms`, `text`, `asr_confidence`, `speaker_tag`, `embed_model_ver` |
| `faster-whisper` | Library | CTranslate2 backend; `pyproject.toml:71` |
| `ctranslate2` | Library | `pyproject.toml:72` |
| `config/models.yaml` | Config | `asr_model`, `asr_compute_type`, `asr_beam_size` |
| GPU host | Infra | `docker/base-gpu.Dockerfile`; 4GB VRAM |
| `src/db/repositories/utterance_repo.py` | Existing | `bulk_insert()` for persisting utterances |

### 4. Requirements Traced

| SRS ID | Requirement | How S19 implements |
|--------|-------------|---------------------|
| FR-2.1 | ASR transcription | `faster-whisper` with `large-v3-turbo` model |
| FR-2.2 | Word-level timestamps | wav2vec2 forced alignment (WhisperX-style) |
| FR-7.8 | Utterance persistence | Bulk insert to `utterances` with all required fields |
| ADR-015 | 4GB VRAM constraint | Sequential model loading; no concurrent GPU models |
| ADR-017 | 8-bit quantization | `int8_float16` for larger models if needed |
| ADR-018 | Local-first ASR | No hosted API; fully local inference |
| NFR-R3 | Durability gate | Transcript committed before downstream stages start |
| NFR-P1 | Real-time factor < 1.0 | Processing 30s chunk in < 30s |

### 5. Interface Contracts

#### 5.1 Worker

```
File: src/workers/asr_worker.py (CREATE)
```

```python
"""ASR worker — transcribes preprocessed audio to word-level utterances."""
from __future__ import annotations

import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

import structlog
from faster_whisper import WhisperModel

from src.core.config import get_settings
from src.db.repositories.utterance_repo import UtteranceRepository

logger = structlog.get_logger()


@dataclass
class Word:
    text: str
    start_ms: int
    end_ms: int
    probability: float


@dataclass
class UtteranceOutput:
    text: str
    start_ms: int
    end_ms: int
    confidence: float
    words: list[Word]


@dataclass
class ASRResult:
    session_id: uuid.UUID
    utterances_count: int
    total_duration_ms: int
    processing_duration_ms: int
    real_time_factor: float  # processing_duration / total_duration


class ASRWorker:
    """Runs faster-whisper with forced alignment on preprocessed audio."""

    def __init__(self) -> None:
        settings = get_settings()
        self._model = WhisperModel(
            settings.ASR_MODEL,
            device=settings.ASR_DEVICE,
            compute_type=settings.ASR_COMPUTE_TYPE,
            cpu_threads=4,
        )

    async def transcribe_session(
        self,
        session_id: uuid.UUID,
        subject_id: uuid.UUID,
        audio_chunks: list[Path],
        vad_regions: list[list[VADRegion]],
    ) -> ASRResult:
        """
        Transcribe all chunks for a session and persist utterances.

        1. Load preprocessed audio (16kHz mono WAV)
        2. Run faster-whisper with VAD regions (skip silence)
        3. Run wav2vec2 forced alignment for word timestamps
        4. Bulk insert utterances to DB
        5. Return ASRResult
        """
        ...

    def transcribe_chunk(
        self,
        audio_path: Path,
        vad_regions: list[VADRegion],
    ) -> list[UtteranceOutput]:
        """Transcribe a single chunk with word-level timestamps."""
        # 1. faster-whisper inference (with VAD regions as initial_prompt hints)
        # 2. wav2vec2 forced alignment for word timestamps
        # 3. Return utterances with text, timestamps, confidence
        ...
```

#### 5.2 Model Configuration

```yaml
# config/models.yaml — existing (already correct)
asr_model: "whisper-large-v3-turbo"
asr_model_revision: "main"
asr_compute_type: "fp16"
asr_device: "cuda"
asr_beam_size: 5
asr_batch_size: 16
```

```python
# src/core/config.py — additions to Settings class
ASR_DEVICE: str = "cuda"
ASR_WORD_TIMESTAMPS: bool = True
ASR_VAD_FILTER: bool = True          # use Silero VAD regions from S17
ASR_CONDITION_ON_PREVIOUS_TEXT: bool = False  # reduce hallucination
ASR_NO_SPEECH_THRESHOLD: float = 0.6  # Whisper no-speech detection
ASR_LOG_PROB_THRESHOLD: float = -1.0  # minimum log-prob for word retention
```

#### 5.3 Utterance Persistence

Uses existing `UtteranceRepository.bulk_insert()` at `src/db/repositories/utterance_repo.py:18`:

```python
# Existing bulk insert SQL:
INSERT INTO utterances (subject_id, session_id, seq, start_ms, end_ms, text,
                       asr_confidence, speaker_tag, embed_model_ver)
VALUES (:subject_id, :session_id, :seq, :start_ms, :end_ms, :text,
        :asr_confidence, :speaker_tag, :embed_model_ver)
```

S19 populates: `subject_id`, `session_id`, `seq` (auto-incremented), `start_ms`, `end_ms`, `text`, `asr_confidence`, `embed_model_ver` (from config). `speaker_tag` is NULL (set by S20).

#### 5.4 SQL DDL

No new tables. Uses existing `utterances` table (S09 migration `c58ea6212bc5`).

### 6. Implementation Notes

**GPU Memory Management (ADR-015):**
- `whisper-large-v3-turbo` at FP16 uses ~2.5GB VRAM
- Must be the **only** GPU model loaded during transcription
- Model loaded once at worker startup, reused across chunks
- If OOM → fall back to `int8_float16` quantization (reduce to ~1.5GB)

**Forced Alignment (FR-2.2):**
- `faster-whisper` provides segment-level timestamps by default
- For word-level timestamps: use wav2vec2 forced alignment (WhisperX approach)
- Alignment model: `jonatasgrosman/wav2vec2-large-xlsr-53-english` or similar
- Word timestamps are required by provenance system (S10 `note_provenance.utterance_id`)

**NFR-R3 Durability Gate:**
- Transcript must be committed to DB-1 before S20 (diarisation) starts
- `bulk_insert()` uses `session.flush()` → data visible in same transaction
- Session status transitions `recording → transcribed` only after all utterances committed
- Downstream stages check session status before starting

**Real-Time Factor (NFR-P1):**
- Target: process 30s chunk in < 30s (RTF < 1.0)
- `whisper-large-v3-turbo` at FP16 achieves ~0.3–0.5 RTF on modern GPU
- For 4GB VRAM GPU: expect ~0.5–0.8 RTF (acceptable)

**Failure Handling:**
- Model load failure → worker exits with error; session stays `recording`
- Transcription failure on one chunk → skip chunk, continue with others
- DB insert failure → retry up to 3 times; if persistent, mark session `failed`
- Worker killed mid-session → on restart, already-transcribed chunks detected by `(session_id, seq)` unique constraint; not reprocessed (T19.5)

### 7. Test Specification

| Test ID | Type | Given | When | Then |
|---------|------|-------|------|------|
| T19.1 | V | S05 held-out set with ground truth transcripts; ASR model loaded | Run transcription on held-out set | WER within 5% of S06 benchmark; WER computed by `src/eval/harness.py` |
| T19.2 | I | Audio fixture with known word timestamps | Run transcription + forced alignment | Word-level timestamps present; timestamps are monotonically increasing; `start_ms < end_ms` for each word |
| T19.3 | I | Session with 50 chunks preprocessed | Run `transcribe_session()` | All utterances persisted in `utterances` table; each has `text`, `start_ms`, `end_ms`, `asr_confidence`, `embed_model_ver`; `speaker_tag` is NULL |
| T19.4 | I | Session with all chunks transcribed | Check session status after `transcribe_session()` completes | `session.status == "transcribed"` (not `recording` or `processing`) |
| T19.5 | I | Session with 30 chunks; worker killed after chunk 15 | Restart worker; run on same session | Only chunks 16–30 reprocessed; chunks 0–15 not re-transcribed (detected by unique constraint) |
| T19.6 | P | 30-minute audio session on GPU host | Run full transcription | Real-time factor < 1.0 (processing completes before session duration) |
| T19.7 | I | Session in `recording` status; no transcript | Attempt to trigger S20 diarisation | S20 refuses to start; status check fails (NFR-R3 gate assertion) |

### 8. Observability

| Metric/Span | Type | Description |
|-------------|------|-------------|
| `lis_asr_chunk_total` | Counter | Incremented per chunk transcribed; labels: `status` (success/failed/skipped) |
| `lis_asr_chunk_duration_ms` | Histogram | Per-chunk transcription time |
| `lis_asr_real_time_factor` | Histogram | RTF per chunk; alerts if > 1.0 |
| `lis_asr_utterance_count` | Histogram | Utterances per chunk |
| `lis_asr_confidence` | Histogram | ASR confidence distribution |
| `lis_asr_model_load_seconds` | Histogram | Time to load model at worker startup |
| `lis_asr_session_total` | Counter | Sessions fully transcribed |

### 9. Rollback

- **How to revert:** Set `ASR_MODEL` to a dummy value; worker will fail to load model and exit gracefully
- **Migration down-path:** N/A (no DDL changes; `utterances` table already exists)
- **Feature flag:** N/A (ASR is core functionality; cannot be skipped)

### 10. Exit Checklist

- [ ] WER on S05 held-out set matches S06 benchmark within tolerance
- [ ] Word-level timestamps present and monotonically increasing
- [ ] Utterances persisted with all required fields
- [ ] Session reaches `transcribed` only after commit
- [ ] Worker killed mid-session → not reprocessed on restart
- [ ] Real-time factor < 1.0 on target GPU
- [ ] Downstream flow rejected if session not `transcribed` (NFR-R3 gate)

---

## S20 ⛔ — Anonymous Diarisation & Transcript Completion (GATE)

### 1. Stage Identity

| Field | Value |
|-------|-------|
| **ID** | S20 |
| **Name** | Anonymous Diarisation & Transcript Completion (GATE) |
| **Block** | B2 — Capture & Ingestion |
| **Owner** | ML + Backend |
| **Estimate** | 2–3 days |
| **Deps** | S19 |
| **SRS** | FR-1.2, NFR-S4, SRS §6 design note |

### 2. Context

Speaker diarisation assigns anonymous tags (`SPK_A`, `SPK_B`, ...) to utterances so the transcript shows who said what during a session. However, per ADR-009 and NFR-S4, **no biometric data may be persisted** — no voiceprints, no embeddings, no cross-session linking. Tags are session-scoped metadata only, dropped at note synthesis.

This stage is the **hard gate** (⛔) for Block 2. When T20.5 passes, the entire ingestion spine is validated end-to-end: record on device → chunks → preprocess → ASR → diarisation → complete transcript in DB-1 with timestamps, confidence, and tags.

**Predecessors:** S19 (ASR utterances in DB-1).

### 3. Dependencies

| Dependency | Type | Notes |
|------------|------|-------|
| S19 | Upstream | Utterances persisted in DB-1 with timestamps and confidence |
| `pyannote.audio` | Library | 3.x for diarisation; NOT in `pyproject.toml` yet — must add |
| GPU host | Infra | Diarisation model runs on GPU; must share with ASR (sequential loading) |
| ADR-009 | Design | Anonymous tags only; zero biometric persistence |
| NFR-S4 | Security | No voiceprint, embedding, or biometric template persisted anywhere |

### 4. Requirements Traced

| SRS ID | Requirement | How S20 implements |
|--------|-------------|---------------------|
| FR-1.2 | Speaker diarisation | pyannote.audio 3.x with anonymous session-scoped tags |
| NFR-S4 | No biometric persistence | Tags are string metadata only; pyannote embeddings discarded immediately |
| SRS §6 | Design note | Tags dropped at note synthesis; never linked across sessions |
| ADR-009 | Anonymous diarisation | Session-local `SPK_A` tags; no voiceprints; optional pipeline component |

### 5. Interface Contracts

#### 5.1 Diarisation Step

```
File: src/ml/diarisation/pyannote.py (CREATE)
```

```python
"""Anonymous speaker diarisation using pyannote.audio 3.x."""
from __future__ import annotations

import uuid
from dataclasses import dataclass

import structlog
from pyannote.audio import Pipeline

from src.core.config import get_settings

logger = structlog.get_logger()


@dataclass
class SpeakerSegment:
    speaker_tag: str   # "SPK_A", "SPK_B", etc.
    start_ms: int
    end_ms: int


@dataclass
class DiarisationResult:
    segments: list[SpeakerSegment]
    num_speakers: int
    duration_ms: int


class PyannoteDiariser:
    """Runs pyannote.audio 3.x diarisation with anonymous tags."""

    def __init__(self) -> None:
        settings = get_settings()
        self._pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            use_auth_token=settings.PYANNOTE_AUTH_TOKEN,
        )

    def diarise(
        self,
        audio_path: str,
        num_speakers: int | None = None,
    ) -> DiarisationResult:
        """
        Run diarisation on audio file.

        Returns anonymous speaker tags (SPK_A, SPK_B, ...).
        No voiceprints, embeddings, or biometric templates are persisted.
        """
        diarization = self._pipeline(
            audio_path,
            num_speakers=num_speakers,
        )

        # Map pyannote speaker labels to anonymous tags
        speaker_map: dict[str, str] = {}
        tag_counter = 0
        segments = []

        for turn, _, speaker in diarization.itertracks(yield_label=True):
            if speaker not in speaker_map:
                speaker_map[speaker] = f"SPK_{chr(65 + tag_counter)}"  # SPK_A, SPK_B, ...
                tag_counter += 1
            segments.append(SpeakerSegment(
                speaker_tag=speaker_map[speaker],
                start_ms=int(turn.start * 1000),
                end_ms=int(turn.end * 1000),
            ))

        return DiarisationResult(
            segments=segments,
            num_speakers=len(speaker_map),
            duration_ms=segments[-1].end_ms if segments else 0,
        )
```

#### 5.2 Speaker Tag Persistence

Updates `utterances.speaker_tag` (existing column from S09 migration):

```sql
-- Already exists:
-- speaker_tag VARCHAR(10) (nullable)
-- No migration needed for S20.
```

```python
# src/workers/diarisation_worker.py (CREATE)

async def assign_speaker_tags(
    session_id: uuid.UUID,
    subject_id: uuid.UUID,
    utterances: list[Utterance],
    diarisation: DiarisationResult,
) -> int:
    """
    Assign speaker tags to utterances based on timestamp overlap.

    For each utterance, find the diarisation segment with maximum temporal overlap
    and assign its speaker_tag. If no overlap, speaker_tag remains NULL.

    Returns count of utterances tagged.
    """
    tagged = 0
    for utt in utterances:
        best_tag = None
        best_overlap = 0
        for seg in diarisation.segments:
            overlap = max(0, min(utt.end_ms, seg.end_ms) - max(utt.start_ms, seg.start_ms))
            if overlap > best_overlap:
                best_overlap = overlap
                best_tag = seg.speaker_tag
        if best_tag and best_overlap > (utt.end_ms - utt.start_ms) * 0.3:  # 30% overlap threshold
            utt.speaker_tag = best_tag
            tagged += 1
    # Bulk update speaker_tag column
    return tagged
```

#### 5.3 Config Keys

```python
# src/core/config.py — additions to Settings class
PYANNOTE_AUTH_TOKEN: str = ""  # from HuggingFace; stored in secrets
DIARISATION_ENABLED: bool = True
DIARISATION_MODEL: str = "pyannote/speaker-diarization-3.1"
DIARISATION_NUM_SPEAKERS: int | None = None  # None = auto-detect
DIARISATION_OVERLAP_THRESHOLD: float = 0.3  # minimum overlap to assign tag
```

#### 5.4 Security Invariants

```python
# CRITICAL: These invariants MUST be verified by T20.2, T20.3

# 1. No pyannote embeddings persisted
#    → pyannote pipeline output is consumed in-memory only
#    → No .save(), no pickle, no numpy.save() on diarization object

# 2. No voiceprint templates persisted
#    → pyannote speaker embeddings are discarded after tag assignment
#    → No embedding column on any diarisation-related table

# 3. Tags are session-local
#    → speaker_tag is VARCHAR(10), not a foreign key
#    → No cross-session tag lookup possible
#    → Tags dropped at note synthesis (A2 input has no speaker info)

# 4. Schema audit
#    → No table has a "voiceprint" or "speaker_embedding" column
#    → No storage object contains biometric data
```

### 6. Implementation Notes

**Pyannote Installation:**
- `pyannote.audio` 3.x must be added to `pyproject.toml` dependencies
- Requires HuggingFace auth token for model download
- Model loaded once at worker startup; reused across sessions

**GPU Memory (4GB VRAM):**
- Diarisation model uses ~1GB VRAM
- Must run **sequentially** with ASR model (cannot coexist in 4GB)
- Sequence: ASR completes → GPU memory freed → diarisation model loaded → diarisation runs

**Optional Pipeline Component (T20.4):**
- Pipeline must complete successfully with diarisation disabled
- `DIARISATION_ENABLED=False` → `speaker_tag` remains NULL for all utterances
- No downstream stage depends on `speaker_tag` being non-NULL

**Speaker Tag Assignment Algorithm:**
- For each utterance, find diarisation segment with maximum temporal overlap
- Assign tag only if overlap > 30% of utterance duration (configurable)
- If no qualifying overlap → `speaker_tag` remains NULL
- Multiple utterances can share the same tag (same speaker)

**Biometric Data Audit (T20.2):**
- Schema audit: verify no table has `voiceprint`, `speaker_embedding`, or similar column
- Storage audit: verify no file in MinIO contains biometric data
- Code audit: verify pyannote embeddings are consumed in-memory only, never serialized

**Failure Handling:**
- Pyannote model load failure → diarisation disabled for session; `speaker_tag = NULL`
- Diarisation inference failure → skip; `speaker_tag = NULL`; pipeline continues
- Never block ASR or session completion on diarisation failure

### 7. Test Specification

| Test ID | Type | Given | When | Then |
|---------|------|-------|------|------|
| T20.1 | I | Session with 100 utterances from a discussion with 3 distinct speakers; pyannote model loaded | Run diarisation and assign speaker tags | Multiple distinct speaker tags assigned (`SPK_A`, `SPK_B`, `SPK_C`); utterances from different speakers have different tags; tags are session-scoped strings |
| T20.2 | S | Full schema audit: all tables, all MinIO buckets, all code paths | Inspect for any voiceprint, embedding, or biometric template persistence | **No voiceprint, embedding, or biometric template of any speaker is persisted anywhere** — verified by schema audit (no such columns), storage audit (no such files), and code audit (pyannote embeddings consumed in-memory only) |
| T20.3 | S | Two sessions with overlapping speakers; diarisation produces `SPK_A` in both | Compare speaker tags across sessions | Tags from session 1 are NOT linkable to tags from session 2; `SPK_A` in session 1 is independent of `SPK_A` in session 2 (session-local metadata only) |
| T20.4 | I | Session with utterances; `DIARISATION_ENABLED=False` | Run pipeline with diarisation disabled | Pipeline completes successfully; all utterances have `speaker_tag = NULL`; session reaches `transcribed` status |
| T20.5 | E | **GATE TEST**: Real audio recording on device (phone) in a real room; full stack running | Record → chunks → upload → preprocess → ASR → diarisation → complete | **End-to-end transcript in DB-1** with: (a) word-level timestamps, (b) ASR confidence scores, (c) speaker tags (or NULL if diarisation disabled), (d) session status = `transcribed`; **T20.5 is the gate — all downstream blocks wait for it to pass** |

### 8. Observability

| Metric/Span | Type | Description |
|-------------|------|-------------|
| `lis_diarisation_session_total` | Counter | Sessions diarised |
| `lis_diarisation_speakers_detected` | Histogram | Number of speakers per session |
| `lis_diarisation_tagged_utterances` | Histogram | Utterances successfully tagged per session |
| `lis_diarisation_duration_ms` | Histogram | Diarisation wall-clock time |
| `lis_diarisation_disabled_total` | Counter | Sessions where diarisation was skipped |
| `lis_gate_block2_passed` | Event | Emitted when T20.5 passes; triggers downstream blocks |

### 9. Rollback

- **How to revert:** Set `DIARISATION_ENABLED=False`; all utterances have `speaker_tag = NULL`; pipeline continues
- **Migration down-path:** N/A (no DDL changes; `speaker_tag` column already exists from S09)
- **Feature flag:**

```python
DIARISATION_ENABLED: bool = True  # set False to skip diarisation entirely
```

### 10. Exit Checklist

- [ ] Speaker tags assigned; multiple distinct speakers detected in discussion session
- [ ] **No voiceprint, embedding, or biometric template persisted anywhere** (NFR-S4)
- [ ] Speaker tags from two sessions are NOT linkable (session-local)
- [ ] Pipeline completes with diarisation disabled (optional component)
- [ ] **⛔ T20.5 passes: end-to-end transcript in DB-1 with timestamps, confidence, and tags**
- [ ] All downstream blocks (B3+) can begin

---

## Cross-Stage Contracts

### Event Flow

```
[S15 PWA] ──chunk──→ [S16 POST /chunks] ──stream──→ [S17 Preprocessing]
                                                          │
                                                    ┌─────┴─────┐
                                                    │ VAD regions │
                                                    └─────┬─────┘
                                                          │
[S16 SSE] ◄──warning── [S18 Quality] ◄──metrics── [S17 output]
                                                          │
                                                    ┌─────┴─────┐
                                                    │  processed  │
                                                    │   audio     │
                                                    └─────┬─────┘
                                                          │
                                                    ┌─────┴─────┐
                                                    │   S19 ASR   │
                                                    └─────┬─────┘
                                                          │
                                                    ┌─────┴─────┐
                                                    │  utterances │
                                                    │   in DB-1   │
                                                    └─────┬─────┘
                                                          │
                                                    ┌─────┴─────┐
                                                    │ S20 Diaris. │
                                                    └─────┬─────┘
                                                          │
                                                    ┌─────┴─────┐
                                                    │  speaker    │
                                                    │   tags      │
                                                    └─────┬─────┘
                                                          │
                                                    ⛔ GATE T20.5
                                                          │
                                                    [Block 3+]
```

### Database State Transitions

```
Session Status:  created ──→ recording ──→ transcribed
                      │           │              │
                      │           │              ▼
                      │           │         processing (Block 3+)
                      │           │              │
                      │           ▼              ▼
                      └─────→ failed ←─────── failed
```

### Valkey Stream Topology

```
Stream: audio.chunk
  ├── Producer: S16 (chunk upload endpoint)
  ├── Consumer Group: preprocessing (S17)
  │   └── Consumer: preprocessing-worker-{pid}
  └── Messages: {session_id, subject_id, seq, timestamp_ms, object_key}
```

### Object Storage Key Scheme

```
lis-audio/
  └── audio/
      └── {session_id}/
          └── {seq:06d}.ogg          # raw chunks from PWA

lis-generated/
  ├── audio/
  │   └── {session_id}/
  │       └── reassembled.wav        # reassembled for ASR
  ├── vad/
  │   └── {session_id}/
  │       └── {seq:06d}.npy          # VAD regions per chunk
  └── diarisation/
      └── {session_id}/
          └── segments.json          # diarisation segments (metadata only)

lis-exports/
  └── notes/
      └── {session_id}/
          └── notes.md               # exported notes (7-day ILM)
```

---

## Appendix A — Files Created by Block 2

| File | Stage | Type | Description |
|------|-------|------|-------------|
| `src/ml/storage.py` | S14 | CREATE | MinIO storage client wrapper |
| `src/core/streams.py` | S16 | CREATE | Valkey Stream producer |
| `src/core/sse.py` | S16 | CREATE | SSE manager for session events |
| `src/core/idempotency.py` | S16 | CREATE | Chunk upload idempotency check |
| `src/api/routes/sessions.py` | S16 | MODIFY | Add chunk upload + SSE + presigned URL endpoints |
| `src/api/schemas/session.py` | S14, S16 | MODIFY | Add `ChunkUploadResponse`, `PresignedURLResponse`, `SessionEvent` |
| `frontend/` | S15 | CREATE | Entire PWA application (React + Vite + Tailwind) |
| `src/ml/preprocessing/chain.py` | S17 | CREATE | Fixed preprocessing chain |
| `src/ml/preprocessing/quality.py` | S18 | CREATE | Audio quality metrics |
| `src/workers/preprocessing_worker.py` | S17 | CREATE | Preprocessing worker |
| `src/workers/asr_worker.py` | S19 | CREATE | ASR worker |
| `src/ml/diarisation/pyannote.py` | S20 | CREATE | Anonymous diarisation |
| `src/workers/diarisation_worker.py` | S20 | CREATE | Diarisation worker |

### Files Modified by Block 2

| File | Stages | Changes |
|------|--------|---------|
| `src/core/config.py` | S14–S20 | Add ~20 new config keys |
| `src/api/routes/sessions.py` | S14, S16 | Add chunk upload, SSE, presigned URL endpoints |
| `src/api/schemas/session.py` | S14, S16 | Add response schemas |
| `pyproject.toml` | S20 | Add `pyannote.audio` dependency |

---

## Appendix B — Config Keys Added

```python
# src/core/config.py — all additions across S14–S20

# S14: Storage
PRESIGNED_URL_EXPIRY_MINUTES: int = 60
AUDIO_CHUNK_FORMAT: str = "ogg"
AUDIO_CHUNK_SAMPLE_RATE: int = 48000

# S15: (Frontend only — no backend config)

# S16: Streams & SSE
VALKEY_STREAM_AUDIO_CHUNK: str = "audio.chunk"
VALKEY_CONSUMER_GROUP_PREPROCESSING: str = "preprocessing"
CHUNK_IDEMPOTENCY_TTL_SECONDS: int = 86400

# S17: Preprocessing
PREPROCESSING_SAMPLE_RATE: int = 16000
PREPROCESSING_TARGET_LUFS: float = -23.0
VAD_THRESHOLD: float = 0.5
VAD_MIN_SPEECH_MS: int = 250
VAD_SPEECH_PADDING_MS: int = 300
DEEPFILTERNET_ENABLED: bool = True
PREPROCESSING_WORKER_CONCURRENCY: int = 1
PREPROCESSING_ENABLED: bool = True

# S18: Quality
QUALITY_SNR_WARNING_THRESHOLD_DB: float = 15.0
QUALITY_SPEECH_RATIO_WARNING_THRESHOLD: float = 0.1
QUALITY_CLIPPING_WARNING_THRESHOLD: float = 0.05
QUALITY_ROLLING_WINDOW_SIZE: int = 5
QUALITY_WARNING_COOLDOWN_SECONDS: int = 60
QUALITY_MONITORING_ENABLED: bool = True

# S19: ASR
ASR_DEVICE: str = "cuda"
ASR_WORD_TIMESTAMPS: bool = True
ASR_VAD_FILTER: bool = True
ASR_CONDITION_ON_PREVIOUS_TEXT: bool = False
ASR_NO_SPEECH_THRESHOLD: float = 0.6
ASR_LOG_PROB_THRESHOLD: float = -1.0

# S20: Diarisation
PYANNOTE_AUTH_TOKEN: str = ""
DIARISATION_ENABLED: bool = True
DIARISATION_MODEL: str = "pyannote/speaker-diarization-3.1"
DIARISATION_NUM_SPEAKERS: int | None = None
DIARISATION_OVERLAP_THRESHOLD: float = 0.3
```

---

## Appendix C — Observability Dashboard

**Block 2 Metrics Summary:**

| Stage | Metrics | Dashboard Panel |
|-------|---------|-----------------|
| S14 | `lis_storage_chunk_upload_total`, `lis_storage_presigned_url_total` | Object Store — Upload Rate |
| S15 | `lis_capture_recording_started`, `lis_capture_chunk_buffered/uploaded/failed` | Client Capture — Recording Status |
| S16 | `lis_chunk_upload_total`, `lis_chunk_upload_latency_ms`, `lis_stream_publish_total` | Ingestion — Chunk Flow |
| S17 | `lis_preprocessing_chunk_total`, `lis_preprocessing_duration_ms`, `lis_preprocessing_speech_ratio` | Preprocessing — Pipeline Health |
| S18 | `lis_quality_chunk_metrics`, `lis_quality_warning_emitted`, `lis_quality_session_score` | Quality — Operator Warnings |
| S19 | `lis_asr_chunk_total`, `lis_asr_real_time_factor`, `lis_asr_confidence` | ASR — Transcription Health |
| S20 | `lis_diarisation_session_total`, `lis_diarisation_speakers_detected`, `lis_gate_block2_passed` | Diarisation — Gate Status |

**Key Alerts:**
- `lis_asr_real_time_factor > 1.0`持续 5 分钟 → GPU degraded
- `lis_quality_warning_emitted` rate > 10/min → widespread audio quality issues
- `lis_chunk_upload_failed` rate > 5% → network or storage degradation
- `lis_gate_block2_passed` not emitted within 24h of first session → pipeline blocked
