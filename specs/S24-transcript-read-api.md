# S24 — Transcript Read API & Client View
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Expose a paginated transcript API filtered by session/subject with relevance and hallucination flags, and build a client transcript view with wavesurfer.js audio scrubbing synced to word timestamps — the first user-visible deliverable that validates timestamp quality by eye.

**Component Boundaries:**
- **Allowed:** `src/api/routes/transcripts.py`, `src/api/schemas/transcripts.py`, `src/services/transcripts/`, `tests/test_transcripts_api.py`, client components
- **Off-limits:** ASR workers (S19, S21), hallucination detection (S22), note synthesis (S44)

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| FastAPI | 0.141.1 | API framework |
| Pydantic | 2.x | Request/response schemas |
| wavesurfer.js | 7.x | Client-side audio waveform + scrubbing |
| pytest | 8.x | Integration tests |
| playwright | 1.x | E2E client tests |

---

### 2. State Machine & Domain Schemas

**Transcript Read Flow:**
```
Client Request
  ├─ GET /transcripts/session/{session_id}    → paginated utterances
  ├─ GET /transcripts/subject/{subject_id}    → aggregated transcripts
  └─ GET /transcripts/utterance/{id}          → single utterance detail

Client Rendering
  → Utterance list with text, timestamps, relevance flags
  → wavesurfer.js waveform visualization
  → Click utterance → play audio at start_ms position
  → Hallucination-flagged utterances shown with indicator
  → Relevance filtering toggle
```

**Pagination Model:**
```
GET /transcripts/session/{session_id}?page=1&page_size=50&include_flagged=false

Response:
{
  "utterances": [...],
  "total": 342,
  "page": 1,
  "page_size": 50,
  "has_next": true,
  "has_prev": false
}
```

**Pydantic Schemas:**
```python
# src/api/schemas/transcripts.py
from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime


class TranscriptUtterance(BaseModel):
    id: UUID
    session_id: UUID
    seq: int
    start_ms: int
    end_ms: int
    text: str
    asr_confidence: float | None = None
    speaker_tag: str | None = None
    is_relevant: bool | None = None
    filter_reason: str | None = None
    asr_agreement: float | None = None
    audio_offset_seconds: float  # start_ms / 1000.0

    model_config = ConfigDict(from_attributes=True)


class TranscriptPage(BaseModel):
    utterances: list[TranscriptUtterance]
    total: int
    page: int
    page_size: int
    has_next: bool
    has_prev: bool


class TranscriptSessionSummary(BaseModel):
    session_id: UUID
    subject_id: UUID
    total_utterances: int
    total_duration_ms: int
    filtered_count: int  # hallucination-flagged utterances
    timestamp_range: tuple[int, int]  # (first_start_ms, last_end_ms)


class TranscriptFilter(BaseModel):
    include_flagged: bool = False
    include_irrelevant: bool = False
    speaker_tag: str | None = None
    min_confidence: float | None = None
    min_agreement: float | None = None
```

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Implement transcript repository with pagination | Query returns correct page of utterances |
| 2 | Implement `/transcripts/session/{session_id}` endpoint | API returns paginated utterances |
| 3 | Implement `/transcripts/subject/{subject_id}` endpoint | API returns aggregated transcripts |
| 4 | Add RLS enforcement (user can only read own transcripts) | Cross-user access rejected |
| 5 | Build client transcript view component | UI renders utterance list |
| 6 | Integrate wavesurfer.js with word timestamps | Click utterance plays correct audio position |
| 7 | Add hallucination flag indicators in UI | Flagged utterances visually distinct |
| 8 | Performance test for large sessions | T24.x pass |

**Atomic Sub-tasks:**
1. Transcript repository with cursor-based pagination
2. FastAPI endpoints with RLS
3. Client transcript list component
4. wavesurfer.js integration with timestamp sync
5. Hallucination flag visual indicators
6. Performance optimization for large sessions

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| Session has no utterances | Return empty list, not 404 |
| Page number exceeds total pages | Return last page (not error) |
| Audio file unavailable | Transcript still renders; audio scrubbing disabled |
| Utterance timestamps out of order | Sort by seq; log warning |
| RLS violation attempt | Return 403 Forbidden |
| Very large session (60+ min) | Cursor-based pagination, lazy loading |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Repository pattern: transcript queries isolated in repository
- Pagination pattern: cursor-based for stability across concurrent writes
- Component pattern: client components are self-contained

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase
- Files: snake_case (`transcripts.py`, `transcript_repo.py`)
- API paths: kebab-case (`/transcripts/session/{session_id}`)

**Code Splitting Metrics:**
- Max function length: 40 lines
- Max file length: 300 lines

**Type Safety:**
- All function signatures typed with Pydantic v2 models
- `from __future__ import annotations` in all files

---

### 5. API & Interface Contracts

**Endpoints:**
```yaml
GET /api/v1/transcripts/session/{session_id}
  Query Parameters:
    page: int (default=1, min=1)
    page_size: int (default=50, min=1, max=200)
    include_flagged: bool (default=false)
    include_irrelevant: bool (default=false)
    speaker_tag: str (optional)
    min_confidence: float (optional)
    min_agreement: float (optional)
  Response: TranscriptPage
  Auth: JWT Bearer, RLS enforced

GET /api/v1/transcripts/subject/{subject_id}
  Query Parameters:
    page: int (default=1, min=1)
    page_size: int (default=50, min=1, max=200)
    include_flagged: bool (default=false)
  Response: TranscriptPage (utterances across all sessions)
  Auth: JWT Bearer, RLS enforced

GET /api/v1/transcripts/utterance/{utterance_id}
  Response: TranscriptUtterance
  Auth: JWT Bearer, RLS enforced
```

**Mock Request/Response Payloads:**
```json
// GET /api/v1/transcripts/session/{session_id}?page=1&page_size=2&include_flagged=true
{
  "utterances": [
    {
      "id": "a1b2c3d4-...",
      "session_id": "e5f6g7h8-...",
      "seq": 0,
      "start_ms": 0,
      "end_ms": 4500,
      "text": "Today we'll cover neural networks and backpropagation",
      "asr_confidence": 0.94,
      "speaker_tag": "SPK_A",
      "is_relevant": true,
      "filter_reason": null,
      "asr_agreement": 0.87,
      "audio_offset_seconds": 0.0
    },
    {
      "id": "i9j0k1l2-...",
      "session_id": "e5f6g7h8-...",
      "seq": 1,
      "start_ms": 4500,
      "end_ms": 8200,
      "text": "Thank you for watching",
      "asr_confidence": 0.31,
      "speaker_tag": null,
      "is_relevant": false,
      "filter_reason": "asr_hallucination",
      "asr_agreement": 0.12,
      "audio_offset_seconds": 4.5
    }
  ],
  "total": 342,
  "page": 1,
  "page_size": 2,
  "has_next": true,
  "has_prev": false
}
```

**RLS Enforcement:**
```sql
-- Transcript queries must include subject_id filter for RLS
SELECT u.* FROM utterances u
JOIN sessions s ON u.session_id = s.id
JOIN subjects sub ON s.subject_id = sub.id
WHERE sub.user_id = $auth_user_id
  AND u.session_id = $session_id
ORDER BY u.seq
LIMIT $page_size OFFSET $offset;
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Default |
|----------|------|-------------|---------|
| `TRANSCRIPT_PAGE_SIZE_DEFAULT` | int | Default page size | `50` |
| `TRANSCRIPT_PAGE_SIZE_MAX` | int | Maximum page size | `200` |
| `TRANSCRIPT_CACHE_TTL_S` | int | Cache TTL for transcript queries | `60` |

**Third-Party Integration Contracts:**
- wavesurfer.js: client-side audio visualization and playback
- FastAPI: API framework with JWT auth

**Version Pins:**
- wavesurfer.js >= 7.x
- FastAPI >= 0.141.1

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T24.1 | I | `pytest tests/test_transcripts_api.py::test_pagination -v` | Pagination correct and stable across pages |
| T24.2 | I | `pytest tests/test_transcripts_api.py::test_rls_enforcement -v` | API returns only the requesting user's transcripts |
| T24.3 | E | `pytest tests/test_transcripts_api.py::test_audio_sync -v` | Clicking an utterance plays correct audio position within 500ms |
| T24.4 | M | Human review on 3 real sessions | Transcript readability and timestamp alignment confirmed |
| T24.5 | P | `pytest tests/test_transcripts_api.py::test_load_performance -v` | Transcript page loads in < 1s for 60-minute session |

**Test Case Details (Given/When/Then):**

**T24.1 — Pagination correct and stable**
- **Given:** a session with 150 utterances
- **When:** pages 1, 2, and 3 are requested with page_size=50
- **Then:** each page returns exactly 50 utterances (except last); seq values are monotonically increasing across pages; no duplicates or gaps

**T24.2 — RLS enforced end to end**
- **Given:** user A has transcripts for subject X; user B has transcripts for subject Y
- **When:** user B requests transcripts for a session belonging to subject X
- **Then:** response is 403 Forbidden or empty list (never user A's data)

**T24.3 — Audio sync within 500ms**
- **Given:** a transcript page with utterances and an audio file
- **When:** the user clicks on an utterance at start_ms=4500
- **Then:** audio playback starts within 500ms of the 4.5s position

**T24.4 — Human review confirms readability**
- **Given:** 3 real lecture sessions with transcripts
- **When:** a human reviewer reads the transcript while listening to audio
- **Then:** transcript text matches audio, timestamps are aligned within ±1s, readability is acceptable

**T24.5 — Page loads in < 1s for 60-minute session**
- **Given:** a 60-minute session with ~3,000 utterances
- **When:** the first page is requested
- **Then:** response time is < 1 second

**Verification Commands:**
```bash
uv run pytest tests/test_transcripts_api.py -v && \
uv run mypy --strict src/api/routes/transcripts.py && \
uv run ruff check src/api/routes/transcripts.py src/services/transcripts/
```

**Exit Criteria:**
- [ ] T24.1 passes — pagination correct and stable
- [ ] T24.2 passes — RLS enforced end to end
- [ ] T24.3 passes — audio sync within 500ms
- [ ] T24.4 passes — human review confirms readability
- [ ] T24.5 passes — page loads in < 1s for 60-minute session

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- Offset-based pagination is unstable under concurrent writes — use cursor-based pagination (seq-based)
- wavesurfer.js loads entire audio file into memory — for very long lectures, use MediaSource extension for chunked loading
- RLS must be enforced at the repository level, not just the API layer — missing subject_id filter bypasses RLS
- Hallucination-flagged utterances must still be returned when `include_flagged=true` — do not silently drop them

**Fallback Instructions:**
- If audio file unavailable: transcript still renders; disable audio scrubbing with "Audio unavailable" message
- If pagination is slow: add composite index on (session_id, seq)
- If RLS fails: log error, reject request, alert operator

**Rollback Procedure:**
- API endpoint can be disabled via feature flag `TRANSCRIPT_API_ENABLED=false`
- No database migration rollback needed
- Client components are independent; can be removed without affecting API

---

### 9. Observability (if applicable)

**Metrics Added:**
- `transcript_api_request_total`: counter of API requests (labels: endpoint, status=success/error)
- `transcript_api_latency_seconds`: histogram of request latency
- `transcript_page_size`: histogram of utterances per page
- `transcript_rls_rejection_total`: counter of RLS rejections

**Tracing/Logging:**
- Span: `transcript.api.request` with attributes (session_id, page, page_size, latency_ms)
- Log: WARN on RLS rejection with user_id and session_id
- Log: INFO on slow queries (> 500ms)

**Alerts:**
- RLS rejection rate > 5%: possible security issue
- API latency P95 > 1s: performance degradation
- Transcript page load > 1s for 60-minute session: index optimization needed

---

### 10. Exit Checklist

- [ ] All tests pass (T24.1, T24.2, T24.3, T24.4, T24.5)
- [ ] Paginated transcript API operational
- [ ] RLS enforced end to end
- [ ] Client transcript view with wavesurfer.js audio scrubbing
- [ ] Hallucination flags visible in UI
- [ ] Audio sync within 500ms
- [ ] **Phase 1 of the SRS is complete and independently useful**
