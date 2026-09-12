# S15 — Client Capture Application (PWA)
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Build a React PWA that records lecture audio in 30s overlapping chunks, buffers to IndexedDB for offline resilience, and uploads with retry — surviving network loss, backgrounding, and tab closure.

**Component Boundaries:**
- **Allowed:** `src/client/` (PWA app), `src/client/components/`, `src/client/services/`, `src/client/hooks/`, `tests/client/`
- **Off-limits:** Server-side chunk upload API (S16), preprocessing (S17), ASR (S19)

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| React | 18.x | UI framework |
| Vite | 5.x | Build tool |
| Tailwind CSS | 3.x | Styling |
| opus-recorder | 0.5.x | Opus encoding |
| idb | 8.x | IndexedDB wrapper |
| Workbox | 7.x | Service worker / offline |

---

### 2. State Machine & Domain Schemas

**Recording State Machine:**
```
IDLE → CONSENT_REQUIRED → RECORDING → STOPPED
                ↓                        ↓
          NO_CONSENT ──────────────→ IDLE
                     RECORDING ────→ PAUSED (backgrounded)
```

**Chunk Schema (client-side):**
```typescript
interface AudioChunk {
  sessionId: string;
  sequence: number;
  blob: Blob;
  startTime: number;  // ms since session start
  endTime: number;
  sampleRate: number;
  createdAt: number;  // Date.now()
}

interface UploadJob {
  id: string;
  sessionId: string;
  chunk: AudioChunk;
  status: 'pending' | 'uploading' | 'completed' | 'failed';
  retries: number;
  uploadUrl?: string;
  error?: string;
}

interface RecordingSession {
  id: string;
  subjectId: string;
  subjectName: string;
  status: 'idle' | 'recording' | 'stopped';
  startedAt: number;
  elapsedMs: number;
  chunkCount: number;
  consentAcknowledged: boolean;
}
```

**IndexedDB Schema (ring buffer):**
```typescript
// DB name: lis-recorder
// Object stores:
//   chunks: keyPath='id', indexes on sessionId, status
//   sessions: keyPath='id'
//   pendingUploads: keyPath='id', index on sessionId
```

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Initialize React + Vite + Tailwind project | `npm run dev` starts without error |
| 2 | Implement subject picker (calls S07 `/subjects` API) | Subject list renders |
| 3 | Implement consent gate with acknowledgement recording | Recording blocked without consent |
| 4 | Implement MediaRecorder + opus-recorder with 30s chunking | Chunks produced at 30s intervals |
| 5 | Implement IndexedDB ring buffer via Workbox | Chunks survive page reload |
| 6 | Implement upload queue with retry and resume | Failed uploads retry on reconnect |
| 7 | Implement session start/stop UI with elapsed timer | Timer shows correct elapsed time |
| 8 | Test offline/resume scenario | NFR-R1: chunks survive network loss |
| 9 | Test backgrounding scenario | Recording continues when backgrounded |
| 10 | Test tab closure scenario | Chunks upload on next app open |

**Atomic Sub-tasks:**
1. React + Vite + Tailwind PWA scaffold
2. Subject picker component (S07 API integration)
3. Consent gate component with acknowledgement
4. Chunked audio recorder (30s overlapping chunks)
5. IndexedDB ring buffer (Workbox service worker)
6. Upload queue with retry and exponential backoff
7. Session start/stop UI with elapsed timer
8. Offline/resume testing

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| Network disconnected mid-session | Chunks buffer to IndexedDB; upload resumes on reconnect (NFR-R1) |
| App backgrounded | MediaRecorder continues; no chunk gap |
| Tab closed mid-session | Buffered chunks upload on next app open |
| Browser lacks MediaRecorder support | Show clear error message, disable recording |
| IndexedDB quota exceeded | Evict oldest completed uploads; alert if still full |
| Opus encoding fails | Fallback to WebM; log warning |
| Upload retry exceeds max | Mark chunk as failed; allow manual retry |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Component pattern: functional React components with hooks
- Service pattern: separate audio recording, upload queue, IndexedDB into service classes
- Observer pattern: upload status updates via event emitter
- Queue pattern: upload queue with retry and backoff

**Naming & Style Guidelines:**
- Components: PascalCase (`SubjectPicker.tsx`)
- Hooks: camelCase with `use` prefix (`useRecorder.ts`)
- Services: PascalCase classes (`UploadQueue.ts`)
- Files: PascalCase for components, camelCase for hooks/services
- Constants: UPPER_SNAKE_CASE

**Code Splitting Metrics:**
- Max component length: 200 lines
- Max hook length: 100 lines
- Max service length: 250 lines

**Type Safety:**
- TypeScript strict mode enabled
- All props and state typed
- No `any` types

---

### 5. API & Interface Contracts

**Subject List (from S07):**
```yaml
GET /api/v1/subjects

Response (200):
  items:
    - id: "550e8400-e29b-41d4-a716-446655440000"
      name: "Operating Systems"
      description: "CS 301"
  total: 1
```

**Session Start (from S07):**
```yaml
POST /api/v1/sessions
Content-Type: application/json

Request:
  subject_id: "550e8400-e29b-41d4-a716-446655440000"
  session_type: "content"

Response (201):
  id: "660e8400-e29b-41d4-a716-446655440000"
  subject_id: "550e8400-e29b-41d4-a716-446655440000"
  status: "created"
```

**Chunk Upload (presigned URL from S14):**
```yaml
PUT {presigned_url}
Content-Type: audio/opus
Body: <binary opus chunk>

Response: 200 OK
```

**SSE Status Stream (from S16):**
```yaml
GET /api/v1/sessions/{id}/stream
Accept: text/event-stream

Events:
  event: status_changed
  data: {"status": "recording", "chunk_count": 5}

  event: audio_warning
  data: {"type": "low_quality", "message": "Audio quality below threshold"}
```

**Consent Acknowledgement Schema:**
```typescript
interface ConsentRecord {
  sessionId: string;
  acknowledgedAt: number;
  consentVersion: string;  // "v1.0"
  userId: string;
}
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Default |
|----------|------|-------------|---------|
| `VITE_API_BASE_URL` | string | Backend API base URL | `http://localhost:8000` |
| `VITE_CHUNK_DURATION_MS` | int | Chunk duration in ms | `30000` |
| `VITE_CHUNK_OVERLAP_MS` | int | Overlap between chunks | `5000` |
| `VITE_MAX_UPLOAD_RETRIES` | int | Max upload retry attempts | `5` |
| `VITE_UPLOAD_RETRY_BASE_MS` | int | Base retry backoff | `1000` |

**Third-Party Integration Contracts:**
- S07 API: `/subjects` endpoint for subject picker
- S14: presigned URL endpoint for chunk upload
- S16: SSE status stream for real-time feedback
- Browser MediaRecorder API: audio capture
- IndexedDB: offline chunk storage

**Version Pins:**
- React >= 18.0
- Vite >= 5.0
- opus-recorder >= 0.5.0
- Workbox >= 7.0

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T15.1 | E | `npm run test -- --grep "60-minute recording"` | 60-minute recording produces expected chunk count with correct overlap |
| T15.2 | E | `npm run test -- --grep "network disconnect"` | Network disconnected → chunks buffer to IndexedDB → upload resumes on reconnect |
| T15.3 | E | `npm run test -- --grep "background foreground"` | App backgrounded then foregrounded → recording continues, no chunk gap |
| T15.4 | U | `npm run test -- --grep "consent gate"` | Recording cannot start without consent acknowledgement |
| T15.5 | U | `npm run test -- --grep "subject required"` | Recording cannot start without a subject selected |
| T15.6 | E | `npm run test -- --grep "tab closure"` | Browser tab closed mid-session → buffered chunks upload on next app open |
| T15.7 | P | `npm run test -- --grep "size check"` | Opus output ≤ 15MB for a 60-minute session |

**Test Case Details (Given/When/Then):**

**T15.1 — 60-minute recording produces expected chunk count**
- **Given:** a recording session starts with 30s chunks and 5s overlap
- **When:** 60 minutes of audio is recorded
- **Then:** approximately 120 chunks are produced (60min / 30s chunks), each ~25s of usable audio with 5s overlap

**T15.2 — Network disconnect buffers and resumes (NFR-R1)**
- **Given:** a recording session is active and chunks are being uploaded
- **When:** the network connection is terminated
- **Then:** chunks buffer to IndexedDB; when network resumes, buffered chunks upload and complete

**T15.3 — Backgrounding does not interrupt recording**
- **Given:** a recording session is active
- **When:** the app is backgrounded (user switches tabs) then foregrounded
- **Then:** MediaRecorder continues; no chunk gap; elapsed timer is accurate

**T15.4 — Recording blocked without consent**
- **Given:** the user has selected a subject but not acknowledged consent
- **When:** the user clicks "Start Recording"
- **Then:** recording does not start; consent gate remains visible

**T15.5 — Recording blocked without subject**
- **Given:** the user has not selected a subject
- **When:** the user attempts to start recording
- **Then:** recording does not start; subject picker is shown

**T15.6 — Tab closure buffers chunks for later upload**
- **Given:** a recording session is active with chunks in IndexedDB
- **When:** the browser tab is closed
- **Then:** on next app open, pending chunks are detected and uploaded

**T15.7 — Opus output within size budget**
- **Given:** a 60-minute recording session
- **When:** all chunks are produced and encoded
- **Then:** total Opus data is ≤ 15MB

**Verification Commands:**
```bash
# Start dev server
cd src/client && npm run dev

# Run unit tests
cd src/client && npm run test

# Run lint
cd src/client && npm run lint

# Build for production
cd src/client && npm run build
```

**Exit Criteria:**
- [ ] T15.1 passes — correct chunk count for 60-minute recording
- [ ] T15.2 passes — network loss resilience (NFR-R1)
- [ ] T15.3 passes — backgrounding does not interrupt
- [ ] T15.4 passes — consent gate enforced
- [ ] T15.5 passes — subject selection required (FR-6.3)
- [ ] T15.6 passes — tab closure chunks upload on next open
- [ ] T15.7 passes — Opus ≤ 15MB for 60-minute session
- [ ] Full lecture records reliably on a real phone in a real room

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- MediaRecorder stops when a tab is backgrounded on some mobile browsers — must use `navigator.mediaSession` API and background audio tricks to keep alive
- IndexedDB writes are async — chunk must be fully written before marking as ready for upload
- Opus-recorder chunk boundaries may not align exactly with 30s — must handle variable-length chunks
- Service worker registration can fail silently — must verify before relying on offline storage
- `getUserMedia` permission must be re-requested on page reload

**Fallback Instructions:**
- If MediaRecorder unavailable: show clear error; disable recording
- If IndexedDB full: evict oldest completed uploads; alert operator
- If upload queue stuck: manual retry button; clear queue option
- If service worker fails to register: fall back to in-memory buffer (no offline resilience)

**Rollback Procedure:**
- PWA is client-only — no database rollback needed
- Service worker can be unregistered via browser DevTools
- No server-side state to rollback
- Feature flag: N/A (client-only)

---

### 9. Observability (if applicable)

**Metrics Added:**
- `recorder_chunk_total`: counter of chunks produced (labels: session_id)
- `recorder_upload_total`: counter of uploads (labels: status=pending/uploading/completed/failed)
- `recorder_upload_latency_ms`: histogram of upload latency
- `recorder_offline_buffer_size`: gauge of chunks in IndexedDB
- `recorder_session_duration_ms`: histogram of session durations

**Tracing/Logging:**
- Log: INFO on session start/stop
- Log: INFO on chunk produced
- Log: WARN on upload failure
- Log: INFO on offline buffer fill/drain
- Log: ERROR on MediaRecorder failure

**Alerts:**
- Offline buffer > 100 chunks: network outage detected
- Upload failure rate > 10%: backend issue

---

### 10. Exit Checklist

- [ ] All tests pass (T15.1–T15.7)
- [ ] PWA installs and works offline (partial)
- [ ] 60-minute recording produces correct chunk count
- [ ] Network loss does not lose chunks (NFR-R1)
- [ ] Consent gate enforced (NFR-S5)
- [ ] Subject selection required (FR-6.3)
- [ ] Opus output within 15MB budget
- [ ] Works on real mobile device in real room
