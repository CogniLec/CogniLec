# S45 — Note Persistence & Idempotency
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Persist A2 output sections + provenance to DB-2 as idempotent upserts keyed on `(session_id, topic_id, ordinal)`, enforce FR-5.6 (reject writes lacking DB-1 records), write section embeddings for retrieval, and set session to `complete` with `notes_ready=true`.

**Component Boundaries:**
- **Allowed:** `src/services/agents/a2/persistence/`, `src/db/repositories/note_repository.py`, `tests/test_note_persistence.py`
- **Off-limits:** A2 synthesis (S44), note API (S46), embedding generation (S48)

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| SQLAlchemy | 2.0.52 | ORM for DB-2 writes |
| pgvector | 0.5.0 | Section embeddings |
| asyncpg | 0.31.0 | Bulk upsert |
| pytest | 8.x | Integration tests |

---

### 2. State Machine & Domain Schemas

**Persistence Flow:**
```
A2SynthesisResult (sections + provenance)
  → FR-5.6 guard: check DB-1 has utterances for this session
  → idempotent upsert: note_sections keyed on (session_id, topic_id, ordinal)
  → insert note_provenance (note_section_id → utterance_id)
  → compute section embeddings
  → write section embeddings
  → set session.notes_ready = true
  → set session.status = complete
```

**Idempotency Key:**
```
UNIQUE (session_id, topic_id, ordinal) on note_sections
  → re-running the same synthesis produces identical output
  → no duplicate sections on re-run (NFR-R6)
```

**FR-5.6 Guard:**
```
BEFORE any DB-2 write:
  SELECT COUNT(*) FROM utterances
  WHERE session_id = $1 AND subject_id = $2
  → if count == 0: REJECT write (no source transcript exists)
  → this prevents notes from existing without their source (AC-6)
```

**Upsert Schema:**
```python
# src/services/agents/a2/persistence/models.py
from pydantic import BaseModel, Field
from uuid import UUID

class NoteSectionUpsert(BaseModel):
    subject_id: UUID
    session_id: UUID
    topic_id: UUID | None = None
    heading: str
    body_md: str
    depth: int
    ordinal: int
    source_utt_ids: list[UUID] = Field(..., min_length=1)
    model_version: str

class NoteProvenanceInsert(BaseModel):
    subject_id: UUID
    note_section_id: UUID
    utterance_id: UUID

class PersistenceResult(BaseModel):
    sections_upserted: int
    provenance_inserted: int
    embeddings_written: int
    session_status: str
    notes_ready: bool
```

**State Transition Rules:**
- Session goes from `processing` → `complete` only after successful DB-2 commit
- `notes_ready` set to `true` only after all sections, provenance, and embeddings are written
- Partial write failure triggers rollback — no orphaned provenance
- Re-running synthesis on same session produces identical output (idempotent)

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Implement FR-5.6 guard: check DB-1 has utterances before DB-2 write | T45.2 passes |
| 2 | Implement idempotent upsert for `note_sections` on `(session_id, topic_id, ordinal)` | T45.1 passes |
| 3 | Implement provenance insert with FK-like validation | Provenance records created |
| 4 | Implement section embedding computation and write | T45.3 passes |
| 5 | Implement partial write rollback (atomic commit or rollback) | T45.4 passes |
| 6 | Implement `notes_ready` flag set only after successful commit | T45.5 passes |
| 7 | Run integration tests | All tests pass |

**Atomic Sub-tasks:**
1. FR-5.6 guard (DB-1 existence check before DB-2 write)
2. Idempotent upsert for `note_sections`
3. Provenance insert with referential validation
4. Section embedding computation
5. Atomic commit/rollback for partial failures
6. Session status update (`complete`, `notes_ready=true`)

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| No DB-1 records for session (FR-5.6) | Reject write, log error, leave session in `processing` |
| Upsert conflict on (session_id, topic_id, ordinal) | Update existing row (idempotent behavior) |
| Provenance references non-existent section | Reject batch, rollback, log error |
| Embedding computation fails | Rollback section write, log error |
| Partial write failure | Atomic rollback — no orphaned data |
| Session already marked `complete` | Skip status update, log info |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Repository pattern: `NoteRepository` encapsulates DB-2 writes
- Guard pattern: FR-5.6 check before any write
- Idempotent pattern: upsert on unique key
- Transaction pattern: atomic commit with rollback

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase (`NoteRepository`, `PersistenceResult`)
- Files: snake_case (`note_repository.py`, `persistence.py`)
- Functions: snake_case (`upsert_sections`, `check_session_exists`)
- Constants: UPPER_SNAKE_CASE (`FR56_GUARD_TABLE`)

**Code Splitting Metrics:**
- Max function length: 40 lines
- Max file length: 300 lines
- Max class methods: 8

**Type Safety:**
- All function signatures typed with Pydantic v2 models
- `from __future__ import annotations` in all files
- Return types explicit on all public methods

---

### 5. API & Interface Contracts

**Note Repository Interface:**
```python
# src/db/repositories/note_repository.py
class NoteRepository:
    async def check_session_has_utterances(
        self,
        session_id: UUID,
        subject_id: UUID,
    ) -> bool:
        """FR-5.6: Check if session has any utterances in DB-1."""
        ...

    async def upsert_sections(
        self,
        sections: list[NoteSectionUpsert],
    ) -> int:
        """Idempotent upsert of note sections. Returns count upserted."""
        ...

    async def insert_provenance(
        self,
        provenance: list[NoteProvenanceInsert],
    ) -> int:
        """Insert provenance records. Returns count inserted."""
        ...

    async def write_section_embeddings(
        self,
        subject_id: UUID,
        section_ids: list[UUID],
        embeddings: list[list[float]],
    ) -> int:
        """Write section embeddings for retrieval. Returns count written."""
        ...

    async def mark_session_complete(
        self,
        session_id: UUID,
        subject_id: UUID,
    ) -> None:
        """Set session.status = 'complete', notes_ready = true."""
        ...
```

**Persistence Orchestrator Interface:**
```python
# src/services/agents/a2/persistence/orchestrator.py
class NotePersistenceOrchestrator:
    def __init__(self, note_repo, utterance_repo, session_repo, embedding_service):
        ...

    async def persist_synthesis(
        self,
        session_id: UUID,
        subject_id: UUID,
        synthesis_result: A2SynthesisResult,
    ) -> PersistenceResult:
        """Persist A2 output to DB-2 with all guards and idempotency.

        1. FR-5.6 guard: verify DB-1 has utterances
        2. Idempotent upsert sections
        3. Insert provenance
        4. Write embeddings
        5. Mark session complete
        """
        ...

    async def _fr56_guard(
        self,
        session_id: UUID,
        subject_id: UUID,
    ) -> None:
        """Reject if no DB-1 records exist for this session."""
        ...
```

**Upsert SQL (PostgreSQL):**
```sql
INSERT INTO note_sections (
    subject_id, id, topic_id, session_id, heading, body_md,
    depth, ordinal, embedding, model_version, created_at, updated_at
) VALUES ($1, gen_random_uuid(), $2, $3, $4, $5, $6, $7, $8, $9, now(), now())
ON CONFLICT (subject_id, session_id, topic_id, ordinal)
DO UPDATE SET
    heading = EXCLUDED.heading,
    body_md = EXCLUDED.body_md,
    depth = EXCLUDED.depth,
    embedding = EXCLUDED.embedding,
    model_version = EXCLUDED.model_version,
    updated_at = now()
RETURNING id;
```

**Provenance Insert SQL:**
```sql
INSERT INTO note_provenance (subject_id, id, note_section_id, utterance_id)
VALUES ($1, gen_random_uuid(), $2, $3);
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Default |
|----------|------|-------------|---------|
| `NOTE_EMBEDDING_MODEL` | string | Model for section embeddings | `tei` |
| `NOTE_EMBEDDING_DIM` | int | Embedding dimension | `1024` |
| `NOTE_PERSISTENCE_BATCH_SIZE` | int | Batch size for upserts | `50` |

**Third-Party Integration Contracts:**
- TEI (S06): section embedding generation
- DB-2 (S10): note_sections, note_provenance tables
- DB-1 (S09): utterances table for FR-5.6 guard

**Version Pins:**
- pgvector pinned in `pyproject.toml`
- asyncpg pinned in `pyproject.toml`

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T45.1 | I | `pytest tests/test_note_persistence.py::test_idempotent_upsert -v` | Re-running flow does not duplicate note sections (NFR-R6) |
| T45.2 | I | `pytest tests/test_note_persistence.py::test_fr56_guard_rejects -v` | DB-2 write for session with no DB-1 record is rejected (AC-6, FR-5.6) |
| T45.3 | I | `pytest tests/test_note_persistence.py::test_embeddings_present -v` | Section embeddings present and queryable |
| T45.4 | I | `pytest tests/test_note_persistence.py::test_partial_write_rollback -v` | Partial write failure rolls back cleanly; no orphaned provenance |
| T45.5 | I | `pytest tests/test_note_persistence.py::test_notes_ready_flag -v` | `notes_ready` set only after successful commit |

**Test Case Details (Given/When/Then):**

**T45.1 — Re-running does not duplicate note sections**
- **Given:** a session with A2 synthesis output producing 8 sections
- **When:** `NotePersistenceOrchestrator.persist_synthesis()` is called twice with the same synthesis result
- **Then:** `note_sections` table contains exactly 8 rows for this session (not 16)

**T45.2 — DB-2 write for session with no DB-1 record is rejected**
- **Given:** a session_id that has no utterances in DB-1
- **When:** `NotePersistenceOrchestrator.persist_synthesis()` is called
- **Then:** `PersistenceError` is raised with message indicating no source transcript, no DB-2 rows created

**T45.3 — Section embeddings present and queryable**
- **Given:** a session with 8 persisted note sections
- **When:** querying `note_sections.embedding` for each section
- **Then:** all 8 sections have non-null `vector(1024)` embeddings that are queryable via pgvector

**T45.4 — Partial write failure rolls back cleanly**
- **Given:** a synthesis result where section 5 of 8 fails to upsert (simulated DB error)
- **When:** `persist_synthesis()` is called
- **Then:** sections 1–4 are rolled back, no orphaned provenance exists, session remains in `processing`

**T45.5 — `notes_ready` set only after successful commit**
- **Given:** a session in `processing` state
- **When:** `persist_synthesis()` completes successfully
- **Then:** `session.status = 'complete'` and `session.notes_ready = true` are set atomically

**Verification Commands:**
```bash
# Full local verification
uv run pytest tests/test_note_persistence.py -v -k "S45 or note_persistence" && \
uv run mypy --strict src/services/agents/a2/persistence/ && \
uv run ruff check src/services/agents/a2/persistence/
```

**Exit Criteria:**
- [ ] T45.1 passes — idempotent upsert, no duplicate sections
- [ ] T45.2 passes — FR-5.6 guard rejects writes without DB-1 records
- [ ] T45.3 passes — section embeddings present and queryable
- [ ] T45.4 passes — partial failure rolls back cleanly
- [ ] T45.5 passes — `notes_ready` set only after successful commit

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- FR-5.6 guard is a hard constraint: notes cannot exist without source transcript — this prevents "phantom notes"
- Idempotency key `(session_id, topic_id, ordinal)` must be enforced at DB level, not just application level
- Partial write failure must trigger full rollback — orphaned provenance breaks note integrity
- `notes_ready` flag must be set atomically with status update — no partial state
- Embedding computation failure should not leave sections without embeddings — rollback or retry

**Fallback Instructions:**
- If FR-5.6 guard fails: do not write to DB-2, leave session in `processing`, alert
- If upsert fails: retry once, then rollback and alert
- If embedding write fails: retry once, then rollback sections and alert
- If session status update fails: retry once, then alert (sections are persisted, status is fixable)

**Rollback Procedure:**
- To undo note persistence: `DELETE FROM note_provenance WHERE session_id=$1; DELETE FROM note_sections WHERE session_id=$1;`
- To reset session: `UPDATE sessions SET status='processing', notes_ready=false WHERE id=$1`
- Feature flag: none needed — persistence is a one-way operation

---

### 9. Observability (if applicable)

**Metrics Added:**
- `note_persistence_total`: counter of persistence calls (labels: status=success/error/rejected)
- `note_persistence_latency_seconds`: histogram of persistence latency
- `note_sections_upserted_total`: histogram of sections upserted per call
- `note_provenance_inserted_total`: histogram of provenance records inserted
- `note_embeddings_written_total`: histogram of embeddings written
- `note_fr56_guard_failures_total`: counter of FR-5.6 guard rejections

**Tracing/Logging:**
- Span: `note.persist` with attributes (session_id, num_sections, num_provenance, latency_ms)
- Log: INFO on persistence completion with section/provenance/embedding counts
- Log: ERROR on FR-5.6 guard failure
- Log: WARNING on partial write rollback

**Alerts:**
- FR-5.6 guard failure rate > 1%: investigate missing DB-1 records
- Persistence latency P95 > 30s: check DB performance
- Partial rollback rate > 5%: investigate DB stability

---

### 10. Exit Checklist

- [ ] All tests pass (T45.1, T45.2, T45.3, T45.4, T45.5)
- [ ] Notes persist idempotently — no duplicate sections on re-run
- [ ] FR-5.6 guard enforced — no DB-2 writes without DB-1 records
- [ ] Section embeddings present and queryable
- [ ] Partial failure rolls back cleanly — no orphaned data
- [ ] `notes_ready` set only after successful commit
