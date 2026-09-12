# S16 — Chunk Upload API & Stream Ingestion
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Accept audio chunks from the PWA, store to MinIO, publish to Valkey Stream for real-time processing, and stream session status back to the client via SSE.

**Component Boundaries:**
- **Allowed:** `src/api/routes/chunks.py`, `src/api/routes/session_stream.py`, `src/services/chunk_ingestion.py`, `src/services/valkey_stream.py`, `tests/test_chunk_upload.py`
- **Off-limits:** Audio preprocessing (S17), ASR (S19), client-side recording (S15)

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| FastAPI | 0.141.1 | API framework |
| boto3 | 1.35.x | MinIO/S3 client |
| valkey (redis-py) | 5.x | Stream producer |
| SSE-Starlette | 1.x | Server-sent events |

---

### 2. State Machine & Domain Schemas

**Session Status Transitions (S16 scope):**
```
created → recording (on first chunk received)
```

**Chunk Ingestion Schema:**
```python
# src/services/chunk_ingestion.py
from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime

class ChunkUploadRequest(BaseModel):
    session_id: UUID
    sequence: int = Field(..., ge=0, description="Chunk sequence number (0-indexed)")
    timestamp_ms: int = Field(..., ge=0, description="Timestamp in ms since session start")
    duration_ms: int = Field(..., gt=0, description="Chunk duration in ms")

class ChunkUploadResponse(BaseModel):
    session_id: UUID
    sequence: int
    stored_key: str
    stream_message_id: str
    status: str  # "stored" | "duplicate"

class StreamMessage(BaseModel):
    event: str = "audio.chunk"
    session_id: UUID
    subject_id: UUID
    sequence: int
    timestamp_ms: int
    duration_ms: int
    object_key: str
    received_at: datetime
```

**Idempotency Layer:**
```
Key: (session_id, seq) → status
  - absent: process chunk, store key
  - present: return duplicate, skip stream publish
```

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Create `POST /sessions/{id}/chunks` endpoint | Endpoint accepts multipart upload |
| 2 | Implement chunk storage to `lis-audio` bucket | Object stored with correct key |
| 3 | Implement idempotency check on `(session_id, seq)` | Duplicate chunk not double-published |
| 4 | Implement Valkey Stream producer (`XADD audio.chunk`) | Message present on stream |
| 5 | Implement session state transition `created → recording` | Session status updated on first chunk |
| 6 | Implement SSE status stream endpoint | Client receives status events |
| 7 | Test concurrent session upload (20 sessions) | No backlog growth (NFR-P7) |
| 8 | Test out-of-order chunk arrival | Stored correctly by sequence |

**Atomic Sub-tasks:**
1. Chunk upload endpoint with file validation
2. Idempotency layer (Redis/Valkey set for dedup)
3. MinIO storage with correct key scheme
4. Valkey Stream producer
5. Session state transition guard
6. SSE status stream endpoint

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| Duplicate chunk `(session, seq)` | Accept, do not double-publish; return `status: "duplicate"` |
| Out-of-order chunk arrival | Store by sequence; stream publish immediately |
| Session not found | Return 404 |
| Session already `complete` | Return 409 Conflict — reject chunk |
| Session `failed` | Return 409 — reject chunk |
| Valkey unavailable | Store chunk; retry stream publish with backoff |
| MinIO unavailable | Return 503; client retries |
| File too large | Reject with 413; max 10MB per chunk |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Endpoint pattern: FastAPI router with dependency injection
- Idempotency pattern: Redis/Valkey SET with NX for deduplication
- Producer pattern: Valkey Stream producer with XADD
- SSE pattern: SSE-Starlette for real-time status

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase
- Files: snake_case (`chunk_upload.py`, `valkey_stream.py`)
- Functions: snake_case
- Constants: UPPER_SNAKE_CASE

**Code Splitting Metrics:**
- Max function length: 40 lines
- Max file length: 300 lines

**Type Safety:**
- All function signatures typed with Pydantic v2 models
- `from __future__ import annotations` in all files

---

### 5. API & Interface Contracts

**Chunk Upload Endpoint:**
```yaml
POST /api/v1/sessions/{session_id}/chunks
Content-Type: multipart/form-data

Form Fields:
  sequence: 0
  timestamp_ms: 0
  duration_ms: 30000
  chunk: <binary opus data>

Response (200):
  session_id: "550e8400-e29b-41d4-a716-446655440000"
  sequence: 0
  stored_key: "550e8400-e29b-41d4-a716-446655440000/chunks/00000.opus"
  stream_message_id: "1726140000000-0"
  status: "stored"

Response (200 — duplicate):
  session_id: "550e8400-e29b-41d4-a716-446655440000"
  sequence: 0
  stored_key: "550e8400-e29b-41d4-a716-446655440000/chunks/00000.opus"
  stream_message_id: ""
  status: "duplicate"

Response (409 — session complete):
  detail: "Session is complete; no more chunks accepted"
```

**SSE Status Stream Endpoint:**
```yaml
GET /api/v1/sessions/{session_id}/stream
Accept: text/event-stream

Events:
  event: status_changed
  data: {"session_id": "...", "status": "recording", "timestamp": "..."}

  event: chunk_received
  data: {"session_id": "...", "sequence": 5, "timestamp": "..."}

  event: audio_warning
  data: {"session_id": "...", "type": "low_quality", "message": "..."}

  event: heartbeat
  data: {"timestamp": "..."}
```

**Valkey Stream Message:**
```yaml
Stream: audio.chunk
Fields:
  session_id: "550e8400-e29b-41d4-a716-446655440000"
  subject_id: "660e8400-e29b-41d4-a716-446655440000"
  sequence: "0"
  timestamp_ms: "0"
  duration_ms: "30000"
  object_key: "550e8400.../chunks/00000.opus"
  received_at: "2026-09-12T10:00:00Z"
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Default |
|----------|------|-------------|---------|
| `VALKEY_HOST` | string | Valkey host | `valkey` |
| `VALKEY_PORT` | int | Valkey port | `6379` |
| `VALKEY_PASSWORD` | string | Valkey password | `changeme` |
| `CHUNK_MAX_SIZE_MB` | int | Max chunk size | `10` |
| `CHUNK_IDEMPOTENCY_TTL_S` | int | Dedup key TTL | `86400` |
| `SSE_HEARTBEAT_INTERVAL_S` | int | SSE heartbeat interval | `30` |

**Third-Party Integration Contracts:**
- MinIO (S14): chunk storage
- Valkey: Stream producer for `audio.chunk`
- S07: session existence check
- S15: client uploads chunks

**Version Pins:**
- FastAPI >= 0.141.1
- redis-py >= 5.0
- SSE-Starlette >= 1.0

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T16.1 | I | `pytest tests/test_chunk_upload.py::test_chunk_stored_and_streamed -v` | Chunk uploaded, stored in MinIO, message present on stream |
| T16.2 | I | `pytest tests/test_chunk_upload.py::test_duplicate_chunk_idempotent -v` | Duplicate chunk accepted and not double-published |
| T16.3 | I | `pytest tests/test_chunk_upload.py::test_out_of_order_chunks -v` | Out-of-order chunks stored correctly by sequence |
| T16.4 | P | `pytest tests/test_chunk_upload.py::test_concurrent_sessions -v` | 20 concurrent sessions sustained without backlog (NFR-P7) |
| T16.5 | I | `pytest tests/test_chunk_upload.py::test_sse_status_events -v` | SSE stream emits status transitions in order |
| T16.6 | I | `pytest tests/test_chunk_upload.py::test_chunk_rejected_after_complete -v` | Chunk for a `complete` session is rejected |

**Test Case Details (Given/When/Then):**

**T16.1 — Chunk stored and streamed**
- **Given:** a session in `created` status exists
- **When:** a chunk is uploaded with sequence 0
- **Then:** chunk is stored in `lis-audio` at `{session_id}/chunks/00000.opus`; message present on `audio.chunk` stream; session status is `recording`

**T16.2 — Duplicate chunk is idempotent**
- **Given:** a chunk with `(session_id, seq=0)` has already been uploaded
- **When:** the same chunk is uploaded again (client retry)
- **Then:** response has `status: "duplicate"`; stream message is NOT published again

**T16.3 — Out-of-order chunks stored correctly**
- **Given:** a session in `recording` status
- **When:** chunks arrive in order seq=2, seq=0, seq=1
- **Then:** all three chunks stored with correct keys; stream messages published for each

**T16.4 — 20 concurrent sessions sustained (NFR-P7)**
- **Given:** 20 concurrent sessions are uploading chunks
- **When:** each session uploads 10 chunks over 5 minutes
- **Then:** all chunks stored; no backlog growth; no dropped messages

**T16.5 — SSE stream emits status transitions**
- **Given:** a client is connected to the SSE stream for a session
- **When:** the session transitions from `created` to `recording`
- **Then:** client receives `status_changed` event with `status: "recording"`

**T16.6 — Chunk rejected after session complete**
- **Given:** a session in `complete` status
- **When:** a new chunk is uploaded
- **Then:** response is 409 Conflict; chunk is not stored

**Verification Commands:**
```bash
uv run pytest tests/test_chunk_upload.py -v -k "S16" && \
uv run mypy --strict src/api/routes/chunks.py src/services/chunk_ingestion.py && \
uv run ruff check src/api/routes/chunks.py src/services/chunk_ingestion.py
```

**Exit Criteria:**
- [ ] T16.1 passes — chunk stored and streamed
- [ ] T16.2 passes — duplicate chunk is idempotent
- [ ] T16.3 passes — out-of-order chunks handled
- [ ] T16.4 passes — 20 concurrent sessions sustained (NFR-P7)
- [ ] T16.5 passes — SSE status transitions emitted
- [ ] T16.6 passes — chunks rejected after session complete

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- Idempotency key `(session_id, seq)` must be stored with TTL — unbounded growth leaks memory
- Valkey `XADD` is fire-and-forget — if consumer is down, messages queue (backpressure handled by consumer)
- Out-of-order chunks must be stored immediately, not buffered for reordering — ASR handles ordering
- SSE connections must have heartbeat to prevent proxy/load balancer timeout
- Session status transition must be atomic with chunk storage — race condition if separate

**Fallback Instructions:**
- If Valkey unavailable: store chunk, retry stream publish with exponential backoff
- If MinIO unavailable: return 503; client retries with backoff
- If SSE connection drops: client reconnects with `Last-Event-ID` header
- If idempotency store unavailable: allow duplicate (safe, just wastes processing)

**Rollback Procedure:**
- No database migrations — API endpoint only
- Stop chunk endpoint: remove route from FastAPI app
- Clear Valkey stream: `DEL audio.chunk`
- Feature flag: `CHUNK_UPLOAD_ENABLED=false` disables the endpoint

---

### 9. Observability (if applicable)

**Metrics Added:**
- `chunk_upload_total`: counter of chunk uploads (labels: status=stored/duplicate/rejected/error)
- `chunk_upload_latency_ms`: histogram of upload processing time
- `chunk_size_bytes`: histogram of chunk sizes
- `chunk_stream_publish_total`: counter of stream messages published (labels: success=true/false)
- `chunk_stream_publish_latency_ms`: histogram of stream publish time
- `session_status_transition_total`: counter of status transitions (labels: from, to)
- `sse_connections_active`: gauge of active SSE connections
- `sse_events_sent_total`: counter of SSE events (labels: event_type)

**Tracing/Logging:**
- Span: `chunk.upload` with attributes (session_id, sequence, size, status)
- Span: `chunk.stream_publish` with attributes (stream, message_id)
- Log: INFO on chunk stored
- Log: WARN on duplicate chunk
- Log: ERROR on storage/publish failure

**Alerts:**
- Chunk upload error rate > 5%: backend issue
- Stream publish failure rate > 1%: Valkey connectivity issue
- SSE connection drop rate > 10%: proxy/load balancer timeout

---

### 10. Exit Checklist

- [ ] All tests pass (T16.1–T16.6)
- [ ] Chunks flow client → object store → stream
- [ ] Idempotency enforced on `(session_id, seq)`
- [ ] SSE status stream functional
- [ ] Session state transitions correctly
- [ ] 20 concurrent sessions sustained (NFR-P7)
- [ ] Chunks rejected after session complete
