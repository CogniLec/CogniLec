# S46 — Note Read API & Client View
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Expose notes API by session and by topic (consolidated across sessions, FR-7.2), build client note view rendering Markdown + KaTeX + Mermaid with provenance affordance (tap section → jump to source transcript position and audio), and topic navigation per subject.

**Component Boundaries:**
- **Allowed:** `src/api/routes/notes.py`, `src/api/schemas/notes.py`, `src/services/notes/`, `tests/test_notes_api.py`, client components
- **Off-limits:** A2 synthesis (S44), note persistence (S45), image retrieval (S62)

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| FastAPI | 0.141.1 | API framework |
| Pydantic | 2.x | Request/response schemas |
| Markdown | 3.x | Markdown rendering |
| KaTeX | 0.16.x | Math rendering |
| Mermaid | 10.x | Diagram rendering |
| pytest | 8.x | Integration tests |

---

### 2. State Machine & Domain Schemas

**Note Read Flow:**
```
Client Request
  ├─ GET /notes/session/{session_id}      → per-session notes
  ├─ GET /notes/topic/{topic_id}          → consolidated topic notes (FR-7.2)
  └─ GET /notes/subject/{subject_id}/nav  → topic navigation tree

Client Rendering
  → Markdown → HTML
  → KaTeX blocks → rendered math
  → Mermaid blocks → rendered diagrams
  → Provenance tap → jump to transcript utterance + audio position
```

**Consolidated Topic Notes (FR-7.2):**
```
topic_id=X across sessions S1, S2, S3
  → merge note_sections from all sessions containing topic X
  → order by session creation date, then ordinal
  → provenance links back to individual session utterances
```

**Provenance Affordance:**
```
tap section → shows source utterance(s)
  → utterance text + audio timestamp (start_ms, end_ms)
  → tap audio → jump to correct position in recording
```

**API Response Schemas:**
```python
# src/api/schemas/notes.py
from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime

class NoteSectionResponse(BaseModel):
    id: UUID
    heading: str
    body_md: str
    depth: int
    ordinal: int
    session_id: UUID
    topic_id: UUID | None = None
    model_version: str | None = None
    created_at: datetime

class ProvenanceLink(BaseModel):
    utterance_id: UUID
    text: str
    start_ms: int
    end_ms: int
    speaker_tag: str | None = None
    audio_offset_seconds: float  # start_ms / 1000

class NoteSectionWithProvenance(BaseModel):
    section: NoteSectionResponse
    provenance: list[ProvenanceLink] = Field(..., min_length=1)

class SessionNotesResponse(BaseModel):
    session_id: UUID
    subject_id: UUID
    topic_id: UUID | None = None
    sections: list[NoteSectionWithProvenance]
    total_sections: int

class ConsolidatedTopicNotesResponse(BaseModel):
    topic_id: UUID
    topic_name: str
    sections: list[NoteSectionWithProvenance]
    source_sessions: list[UUID]  # sessions contributing to these notes
    total_sections: int

class TopicNavItem(BaseModel):
    topic_id: UUID
    topic_name: str
    section_count: int
    session_count: int

class SubjectNavigationResponse(BaseModel):
    subject_id: UUID
    topics: list[TopicNavItem]
```

**State Transition Rules:**
- Read-only API — no state transitions
- RLS enforced: users can only read notes for their own subjects
- Per-session notes are from a single session's synthesis
- Consolidated topic notes merge across all sessions containing that topic

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Define API request/response Pydantic schemas in `src/api/schemas/notes.py` | Schemas import, validate sample payloads |
| 2 | Implement `GET /api/v1/notes/session/{session_id}` endpoint | T46.1 passes |
| 3 | Implement `GET /api/v1/notes/topic/{topic_id}` endpoint (consolidated, FR-7.2) | T46.2 passes |
| 4 | Implement `GET /api/v1/notes/subject/{subject_id}/navigation` endpoint | Topic nav tree returned |
| 5 | Implement provenance links with audio offset calculation | T46.3 passes |
| 6 | Implement RLS check (no cross-user note access) | T46.5 passes |
| 7 | Build client note view component with Markdown/KaTeX/Mermaid rendering | T46.4 passes |
| 8 | Implement provenance tap → transcript/audio jump | T46.3, T46.4 pass |
| 9 | Performance benchmark | T46.6 passes |
| 10 | Run full integration test suite | All tests pass |

**Atomic Sub-tasks:**
1. API Pydantic schemas for notes read responses
2. Per-session notes endpoint
3. Consolidated topic notes endpoint (FR-7.2)
4. Subject topic navigation endpoint
5. Provenance links with audio offset
6. RLS enforcement
7. Client note view with Markdown/KaTeX/Mermaid rendering
8. Provenance tap → transcript/audio navigation
9. Performance optimization for note page load

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| Session has no notes (notes_ready=false) | Return 404 with descriptive error |
| Topic has no notes across any session | Return empty list, 200 |
| Consolidated topic merges 0 sections | Return empty list, 200 |
| Provenance references deleted utterance | Skip invalid provenance, log warning |
| Mermaid block has syntax error | Return raw block, client shows error state |
| KaTeX block has render error | Return raw block, client shows error state |
| RLS denies access | Return 403 Forbidden |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Repository pattern: `NoteReadRepository` for DB-2 reads
- API router pattern: FastAPI router with dependency injection
- Builder pattern: `ConsolidatedNotesBuilder` for merging across sessions
- Presenter pattern: client note view with Markdown/KaTeX/Mermaid rendering

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase (`NoteReadRepository`, `SessionNotesResponse`)
- Files: snake_case (`notes.py`, `notes_repository.py`)
- Functions: snake_case (`get_session_notes`, `get_consolidated_topic_notes`)
- API paths: kebab-case or lowercase (`/api/v1/notes/session/{id}`)

**Code Splitting Metrics:**
- Max function length: 40 lines
- Max file length: 300 lines
- Max class methods: 8

**Type Safety:**
- All function signatures typed with Pydantic v2 models
- `from __future__ import annotations` in all files
- Return types explicit on all public methods
- API endpoints return Pydantic models, not dicts

---

### 5. API & Interface Contracts

**API Endpoints:**
```yaml
# src/api/routes/notes.py
openapi:
  /api/v1/notes/session/{session_id}:
    get:
      summary: Get notes for a specific session
      parameters:
        - name: session_id
          in: path
          required: true
          schema:
            type: string
            format: uuid
      responses:
        200:
          description: Session notes with provenance
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/SessionNotesResponse'
        404:
          description: Session not found or notes not ready

  /api/v1/notes/topic/{topic_id}:
    get:
      summary: Get consolidated topic notes across all sessions (FR-7.2)
      parameters:
        - name: topic_id
          in: path
          required: true
          schema:
            type: string
            format: uuid
      responses:
        200:
          description: Consolidated topic notes with provenance
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ConsolidatedTopicNotesResponse'

  /api/v1/notes/subject/{subject_id}/navigation:
    get:
      summary: Get topic navigation tree for a subject
      parameters:
        - name: subject_id
          in: path
          required: true
          schema:
            type: string
            format: uuid
      responses:
        200:
          description: Topic navigation tree
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/SubjectNavigationResponse'
```

**Note Read Repository Interface:**
```python
# src/db/repositories/note_read_repository.py
class NoteReadRepository:
    async def get_session_notes(
        self,
        session_id: UUID,
        subject_id: UUID,
    ) -> list[NoteSectionWithProvenance]:
        """Get all note sections with provenance for a session."""
        ...

    async def get_topic_notes_consolidated(
        self,
        topic_id: UUID,
        subject_id: UUID,
    ) -> ConsolidatedTopicNotesResponse:
        """Get consolidated notes for a topic across all sessions (FR-7.2)."""
        ...

    async def get_subject_navigation(
        self,
        subject_id: UUID,
    ) -> SubjectNavigationResponse:
        """Get topic navigation tree for a subject."""
        ...

    async def get_provenance_for_section(
        self,
        section_id: UUID,
        subject_id: UUID,
    ) -> list[ProvenanceLink]:
        """Get provenance links with audio offset for a section."""
        ...
```

**Client Note View Component:**
```typescript
// client/components/NoteView.tsx
interface NoteViewProps {
  sections: NoteSectionWithProvenance[];
  onProvenanceTap: (utteranceId: string, audioOffset: number) => void;
}

// Renders:
// - Markdown body via react-markdown
// - KaTeX blocks via react-katex
// - Mermaid blocks via mermaidmaid
// - Provenance links with tap-to-jump
```

**Provenance Navigation:**
```typescript
// When user taps a provenance link:
onProvenanceTap(utteranceId: string, audioOffset: number) {
  // 1. Scroll transcript view to utteranceId
  // 2. Seek audio player to audioOffset seconds
  // 3. Highlight the source utterance
}
```

**Mock Request/Response Payloads:**
```json
// GET /api/v1/notes/session/uuid-session-001
{
  "session_id": "uuid-session-001",
  "subject_id": "uuid-subject-001",
  "topic_id": "uuid-topic-001",
  "sections": [
    {
      "section": {
        "id": "uuid-section-001",
        "heading": "Eigenvalues and Eigenvectors",
        "body_md": "## Eigenvalues\n\nAn eigenvalue $$\\lambda$$ of matrix A satisfies...",
        "depth": 1,
        "ordinal": 0,
        "session_id": "uuid-session-001",
        "topic_id": "uuid-topic-001",
        "model_version": "tier_1",
        "created_at": "2026-09-12T10:00:00Z"
      },
      "provenance": [
        {
          "utterance_id": "uuid-utt-001",
          "text": "So eigenvalues are scalars that satisfy Av = lambda v",
          "start_ms": 120000,
          "end_ms": 135000,
          "speaker_tag": "lecturer",
          "audio_offset_seconds": 120.0
        },
        {
          "utterance_id": "uuid-utt-002",
          "text": "Can you show us how to compute them?",
          "start_ms": 136000,
          "end_ms": 140000,
          "speaker_tag": "student",
          "audio_offset_seconds": 136.0
        }
      ]
    }
  ],
  "total_sections": 8
}
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Default |
|----------|------|-------------|---------|
| `NOTES_API_PREFIX` | string | API route prefix | `/api/v1/notes` |
| `NOTES_RLS_ENABLED` | bool | Enable RLS enforcement | `true` |
| `NOTES_CACHE_TTL` | int | Cache TTL in seconds | `300` |
| `NOTES_MAX_SECTIONS` | int | Max sections per response | `100` |

**Third-Party Integration Contracts:**
- FastAPI (S07): API framework and dependency injection
- DB-2 (S10): note_sections, note_provenance tables
- Auth (S12): RLS enforcement for multi-user

**Version Pins:**
- FastAPI pinned in `pyproject.toml`
- Markdown/KaTeX/Mermaid pinned in client `package.json`

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T46.1 | I | `pytest tests/test_notes_api.py::test_get_session_notes -v` | Per-session notes returned correctly |
| T46.2 | I | `pytest tests/test_notes_api.py::test_consolidated_topic_notes -v` | Consolidated topic notes merge content across all sessions (FR-7.2) |
| T46.3 | E | `pytest tests/test_notes_api.py::test_provenance_navigates -v` | Provenance tap navigates to correct transcript utterance and audio position |
| T46.4 | E | `pytest tests/test_notes_api.py::test_katex_mermaid_render -v` | KaTeX and Mermaid render correctly in the client |
| T46.5 | I | `pytest tests/test_notes_api.py::test_rls_no_cross_user -v` | RLS verified: no cross-user note access |
| T46.6 | P | `pytest tests/test_notes_api.py::test_note_page_load_perf -v` | Note page loads in < 3s (NFR-P4) |

**Test Case Details (Given/When/Then):**

**T46.1 — Per-session notes returned correctly**
- **Given:** a session with 8 note sections and provenance
- **When:** `GET /api/v1/notes/session/{session_id}` is called
- **Then:** response contains 8 sections with valid provenance links, status 200

**T46.2 — Consolidated topic notes merge across all sessions**
- **Given:** topic "Linear Algebra" appears in sessions S1 (3 sections), S2 (5 sections), S3 (2 sections)
- **When:** `GET /api/v1/notes/topic/{topic_id}` is called
- **Then:** response contains 10 sections ordered by session creation date, with `source_sessions` listing S1, S2, S3

**T46.3 — Provenance tap navigates to correct transcript and audio**
- **Given:** a note section with provenance link to utterance `uuid-utt-001` at `start_ms=120000`
- **When:** user taps the provenance link in the client
- **Then:** transcript view scrolls to `uuid-utt-001` and audio player seeks to 120.0 seconds

**T46.4 — KaTeX and Mermaid render correctly**
- **Given:** a note section with KaTeX math (`$$E = mc^2$$`) and Mermaid diagram (`graph TD`)
- **When:** client renders the note section
- **Then:** KaTeX renders as formatted math, Mermaid renders as a diagram

**T46.5 — RLS verified: no cross-user note access**
- **Given:** user A owns subject S1, user B owns subject S2
- **When:** user A calls `GET /api/v1/notes/session/{session_in_S2}`
- **Then:** response is 403 Forbidden (RLS enforced)

**T46.6 — Note page loads in < 3s**
- **Given:** a session with 20 note sections and provenance
- **When:** `GET /api/v1/notes/session/{session_id}` is called
- **Then:** response latency is < 3s (NFR-P4)

**Verification Commands:**
```bash
# Full local verification
uv run pytest tests/test_notes_api.py -v -k "S46 or notes_api" && \
uv run mypy --strict src/api/routes/notes.py src/api/schemas/notes.py && \
uv run ruff check src/api/routes/notes.py src/api/schemas/notes.py
```

**Exit Criteria:**
- [ ] T46.1 passes — per-session notes returned correctly
- [ ] T46.2 passes — consolidated topic notes merge across sessions (FR-7.2)
- [ ] T46.3 passes — provenance tap navigates to correct transcript and audio
- [ ] T46.4 passes — KaTeX and Mermaid render correctly
- [ ] T46.5 passes — RLS enforced, no cross-user access
- [ ] T46.6 passes — note page loads in < 3s (NFR-P4)

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- Consolidated topic notes must order by session creation date, not section creation date — sections from earlier sessions appear first
- Provenance audio offset is `start_ms / 1000` — floating point precision matters for seek accuracy
- RLS must be enforced at the query level, not just the API level — SQL-level Row Level Security
- Mermaid rendering is client-side — large diagrams may cause performance issues
- KaTeX rendering blocks are pre-validated by A2 (S44) — client trusts server output
- Consolidated topic notes across many sessions can be large — pagination may be needed

**Fallback Instructions:**
- If note page load exceeds 3s: add pagination, reduce provenance depth, cache frequently accessed notes
- If Mermaid rendering fails: show raw Mermaid block with error indicator
- If KaTeX rendering fails: show raw LaTeX with error indicator
- If RLS check fails: return 403, log security event

**Rollback Procedure:**
- API endpoints are read-only — no data changes to rollback
- Client rendering changes are versioned — roll back client version if rendering breaks
- Feature flag: `NOTES_RLS_ENABLED=false` disables RLS (development only, never in production)

---

### 9. Observability (if applicable)

**Metrics Added:**
- `notes_api_request_total`: counter of API requests (labels: endpoint, status=200/404/403)
- `notes_api_latency_seconds`: histogram of API response latency
- `notes_consolidated_sections_total`: histogram of sections returned for consolidated queries
- `notes_provenance_tap_total`: counter of provenance tap events (client-side)
- `notes_render_total`: counter of note render events (labels: status=success/error)

**Tracing/Logging:**
- Span: `notes.get_session` with attributes (session_id, num_sections, latency_ms)
- Span: `notes.get_topic` with attributes (topic_id, num_sessions, num_sections, latency_ms)
- Log: INFO on successful note retrieval
- Log: WARNING on RLS denial (security event)
- Log: ERROR on DB query failure

**Alerts:**
- Note page load P95 > 3s: investigate DB performance or add caching
- RLS denial rate > 1%: investigate access patterns, possible security issue
- Consolidated query returns > 100 sections: consider pagination

---

### 10. Exit Checklist

- [ ] All tests pass (T46.1, T46.2, T46.3, T46.4, T46.5, T46.6)
- [ ] Per-session notes endpoint functional
- [ ] Consolidated topic notes merge across all sessions (FR-7.2)
- [ ] Provenance tap navigates to correct transcript and audio position
- [ ] KaTeX and Mermaid render correctly in the client
- [ ] RLS enforced: no cross-user note access
- [ ] Note page loads in < 3s (NFR-P4)
- [ ] **The core product exists — users can read topic-organised, verifiable notes**
