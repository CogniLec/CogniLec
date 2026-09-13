# S50 — A6 Syllabus Extraction
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** A6 extracts structured syllabus items (topic/module hierarchy, ordinals, assessment structure, references, stated schedule) from a syllabus-lecture transcript and writes them exclusively to DB-3 — making A6 the sole writer to the syllabus store.

**Component Boundaries:**
- **Allowed:** `src/agents/a6/`, `src/services/syllabus/`, `src/db/repositories/syllabus_repo.py`, `config/schemas/a6_syllabus.py`, `tests/test_a6_syllabus.py`, `tests/test_syllabus_write_authority.py`
- **Off-limits:** FDW link setup (S11 — already done), coverage mapping (S52), topic-to-syllabus alignment, PG-MAIN schema, A1–A5 agent implementations

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| Pydantic | 2.x | Extraction output schema |
| SQLAlchemy | 2.0.52 | DB-3 write path |
| Outlines / XGrammar | latest | Grammar-constrained decoding for local model output |
| Instructor | 1.x | Structured output for hosted tier fallback |
| pytest | 8.x | Integration tests |
| testcontainers | 4.6.x | PG-SYLLABUS container for tests |

---

### 2. State Machine & Domain Schemas

**A6 Extraction Flow:**
```
transcript_chunk → A6 agent (LLM) → structured syllabus items → schema validation → DB-3 write
                                              ↓
                              grade_of_authority ≤ 2 (certainty gate)
```

**Extraction State:**
```
PENDING → EXTRACTING → VALIDATED → WRITTEN
                       ↓ (schema fail)
                    FAILED (logged, not retried automatically)
```

**Syllabus Item Extraction Schema:**
```python
# config/schemas/a6_syllabus.py
from pydantic import BaseModel, Field
from enum import Enum


class ItemType(str, Enum):
    MODULE = "module"
    TOPIC = "topic"
    SUBTOPIC = "subtopic"
    ASSESSMENT = "assessment"
    REFERENCE = "reference"
    SCHEDULE = "schedule"


class ExtractedSyllabusItem(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    item_type: ItemType
    ordinal: int = Field(..., ge=0)
    parent_ordinal: int | None = Field(None, ge=0)  # None = top-level
    description: str | None = Field(None, max_length=5000)
    weight_pct: float | None = Field(None, ge=0.0, le=100.0)  # for assessments
    week_number: int | None = Field(None, ge=1)  # for schedule items
    references: list[str] = Field(default_factory=list, max_length=20)


class A6SyllabusOutput(BaseModel):
    items: list[ExtractedSyllabusItem] = Field(..., min_length=1, max_length=200)
    subject_title: str = Field(..., min_length=1, max_length=500)
    extraction_confidence: float = Field(..., ge=0.0, le=1.0)
    grade_of_authority: int = Field(..., ge=1, le=5)  # ≤ 2 = high certainty
```

**Pydantic Response Model:**
```python
# src/api/schemas/syllabus.py
class SyllabusItemResponse(BaseModel):
    id: UUID
    subject_id: UUID
    parent_id: UUID | None
    ordinal: int
    title: str
    description: str | None
    item_type: str
    weight_pct: float | None
    week_number: int | None
    references: list[str]
    source: str  # "lecture" | "upload" | "manual"
    source_session_id: UUID | None
    coverage_status: str  # "not_started" | "partial" | "covered"
    covered_by: list[UUID]
    embedding: list[float] | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
```

**State Transition Rules:**
- Transcript arrives → routed to A6 if session is classified as syllabus lecture
- A6 extracts items with ordinals → validated against `A6SyllabusOutput` schema
- Schema validation passes → items written to DB-3 (PG-SYLLABUS) with `source='lecture'`
- Schema validation fails → logged as FAILED, no retry, no partial writes
- Grade of authority > 2 → extraction rejected (low confidence), logged as rejected
- Mixed session syllabus segment → only the syllabus portion routed to A6 (AC-13)

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Define `A6SyllabusOutput` Pydantic schema with grammar constraint | Schema imports, compiles grammar for local model |
| 2 | Create `src/agents/a6/__init__.py` with A6 agent class | Agent instantiates, loads schema from registry |
| 3 | Implement transcript chunker for syllabus lectures | Unit test: raw transcript → chunked segments |
| 4 | Implement extraction pipeline: chunk → LLM → validated output | Unit test: mock LLM returns valid items |
| 5 | Implement DB-3 write path via `SyllabusRepository` | Integration test: items land in PG-SYLLABUS |
| 6 | Add write-authority enforcement: only A6 can write to DB-3 | Security test: other agents' writes rejected at DB level |
| 7 | Add embedding generation for extracted items | Items have embeddings computed via S48 pipeline |
| 8 | Wire session routing: syllabus lectures → A6 | Integration test: syllabus session triggers A6 extraction |
| 9 | Wire mixed-session segment isolation | Integration test: syllabus segment extracted from mixed session (AC-13) |
| 10 | Run 20-real-syllabus extraction eval | T50.5: accuracy ≥ 0.85 |

**Atomic Sub-tasks:**
1. A6 agent class with schema registry integration
2. Transcript chunking logic for syllabus lectures
3. LLM extraction pipeline with grammar-constrained decoding
4. Schema validation with bounded retry (hosted tier)
5. DB-3 write path with repository pattern
6. Write-authority enforcement at DB and application level
7. Embedding generation for extracted items
8. Session routing: syllabus lecture → A6 pipeline
9. Mixed-session syllabus segment isolation
10. Evaluation harness for extraction accuracy

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| Transcript contains no syllabus content | A6 returns empty items list, logged as "no syllabus content found", no DB write |
| Schema validation fails | Output rejected, logged with raw LLM output, no partial writes |
| Grade of authority > 2 | Extraction rejected, logged as low-confidence, not written to DB-3 |
| DB-3 (PG-SYLLABUS) unavailable | Write fails with error, extraction result cached in memory, retry on next attempt |
| Duplicate item ordinals | Application-level deduplication by title; same ordinal + same parent = merge descriptions |
| Hierarchy depth > 5 | Flatten deepest level into description of parent |
| Non-A6 agent attempts DB-3 write | Rejected at DB level: GRANT only to A6 role (FR-3.8) |
| Mixed session with partial syllabus | Syllabus segment identified and isolated, only that segment sent to A6 |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Agent pattern: `A6Agent` class with `extract(transcript) → A6SyllabusOutput`
- Repository pattern: `SyllabusRepository` for DB-3 writes
- Registry pattern: schema loaded from `SchemaRegistry` (S38)
- Pipeline pattern: chunk → extract → validate → embed → write

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase (`A6Agent`, `SyllabusRepository`)
- Files: snake_case (`a6_agent.py`, `syllabus_extraction.py`)
- Schema files: `config/schemas/a6_syllabus.py`
- Constants: UPPER_SNAKE_CASE (`MAX_HIERARCHY_DEPTH = 5`)

**Code Splitting Metrics:**
- Max function length: 40 lines
- Max file length: 300 lines
- Max class methods: 8

**Type Safety:**
- All function signatures typed with Pydantic v2 models
- `from __future__ import annotations` in all files
- Return types explicit on all public methods
- Enum types for item types and source

---

### 5. API & Interface Contracts

**A6 Agent Interface:**
```python
# src/agents/a6/agent.py
class A6Agent:
    async def extract(self, transcript: TranscriptChunk, subject_id: UUID) -> A6SyllabusOutput:
        """Extract structured syllabus items from a transcript chunk.

        Returns validated output with grade_of_authority ≤ 2.
        Raises ExtractionRejected if confidence too low.
        """
        ...

    async def extract_from_mixed_session(
        self, full_transcript: Transcript, syllabus_segment: Segment
    ) -> A6SyllabusOutput:
        """Extract from an isolated syllabus segment of a mixed session."""
        ...
```

**DB-3 Write Path:**
```python
# src/db/repositories/syllabus_repo.py
class SyllabusRepository:
    async def bulk_create_items(
        self,
        subject_id: UUID,
        items: list[ExtractedSyllabusItem],
        source_session_id: UUID | None = None,
        source: str = "lecture",
    ) -> list[SyllabusItem]:
        """Bulk insert syllabus items into PG-SYLLABUS.

        Only callable by A6 agent (write-authority enforced at DB role level).
        """
        ...

    async def get_tree(self, subject_id: UUID) -> SyllabusTree:
        """Get full syllabus tree for a subject (read via FDW from PG-MAIN)."""
        ...

    async def upsert_item(
        self, subject_id: UUID, item: ExtractedSyllabusItem, source_session_id: UUID | None = None
    ) -> SyllabusItem:
        """Upsert a single item (update if title + parent match)."""
        ...
```

**Write-Authority Enforcement:**
```sql
-- PG-SYLLABUS: only A6 role can write
CREATE ROLE a6_writer WITH LOGIN PASSWORD '...';
GRANT INSERT, UPDATE, DELETE ON syllabus_items TO a6_writer;
REVOKE ALL ON syllabus_items FROM PUBLIC;

-- PG-MAIN FDW user: read-only
GRANT SELECT ON FOREIGN TABLE syllabus_items TO lis;
-- lis has NO INSERT/UPDATE/DELETE on syllabus_items
```

```python
# src/db/write_guard.py
class DB3WriteGuard:
    """Enforce that only A6 agent can write to DB-3.

    Application-level guard that wraps SyllabusRepository write operations.
    Logs and rejects any write attempt not originating from A6 context.
    """

    _a6_context: ContextVar[bool] = ContextVar("a6_write_context", default=False)

    @classmethod
    @contextmanager
    def a6_write_context(cls):
        token = cls._a6_context.set(True)
        try:
            yield
        finally:
            cls._a6_context.reset(token)

    @classmethod
    def check_write_authority(cls) -> None:
        if not cls._a6_context.get():
            raise PermissionError(
                "DB-3 write rejected: only A6 agent may write to syllabus store (FR-3.8)"
            )
```

**Session Routing:**
```python
# src/graph/t4_subgraph.py (addition)
def route_syllabus_lecture(session_type: str, transcript: Transcript) -> str:
    """Route syllabus lectures to A6 extraction pipeline.

    If session is classified as 'syllabus' → A6 extraction.
    If session is 'mixed' and contains syllabus segment → isolate and route to A6.
    Otherwise → normal topic extraction (no A6 involvement).
    """
    ...
```

**Event Contract:**
```json
{
  "event": "syllabus.extracted",
  "session_id": "uuid",
  "subject_id": "uuid",
  "item_count": 15,
  "confidence": 0.92,
  "grade_of_authority": 1,
  "timestamp": "2026-09-12T10:30:00Z"
}
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Default |
|----------|------|-------------|---------|
| `SYLLABUS_DATABASE_URL` | string | PG-SYLLABUS direct connection (for writes) | `postgresql://a6_writer:...@pg-syllabus:5432/lis_syllabus` |
| `A6_MODEL_TIER` | string | Model tier for A6 extraction | `tier1_local` |
| `A6_EXTRACTION_CONFIDENCE_MIN` | float | Minimum grade of authority to accept | `2` |
| `A6_MAX_ITEMS_PER_TRANSCRIPT` | int | Max syllabus items extracted per transcript | `200` |
| `A6_GRAMMAR_CACHE_DIR` | string | Compiled grammar cache for Outlines | `/tmp/a6_grammar` |

**Third-Party Integration Contracts:**
- Outlines/XGrammar: grammar-constrained decoding for local model (S38)
- Instructor: structured output for hosted tier (S38)
- S48 embedding pipeline: compute embeddings for extracted items
- S35 session router: classify and route syllabus lectures to A6

**Version Pins:**
- Pydantic 2.x pinned in `pyproject.toml`
- SQLAlchemy 2.0.52 pinned in `pyproject.toml`
- Outlines/XGrammar pinned in `pyproject.toml`

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T50.1 | I | `pytest tests/test_a6_syllabus.py::test_syllabus_lecture_capture_path -v` | Syllabus lecture follows identical capture/ASR path as content lecture (FR-2.17) |
| T50.2 | I | `pytest tests/test_a6_syllabus.py::test_items_land_in_db3 -v` | Extracted items are in DB-3 (PG-SYLLABUS), NOT in DB-2 |
| T50.3 | I | `pytest tests/test_a6_syllabus.py::test_hierarchy_ordinals -v` | Item hierarchy and ordinals are correct after extraction |
| T50.4 | S | `pytest tests/test_syllabus_write_authority.py::test_only_a6_writes_db3 -v` | No agent other than A6 can write to DB-3 (FR-3.8, permissions at DB level) |
| T50.5 | V | `pytest tests/test_a6_syllabus.py::test_extraction_accuracy_20_syllabi -v` | Extraction accuracy ≥ 0.85 on 20 real syllabus transcripts |
| T50.6 | I | `pytest tests/test_a6_syllabus.py::test_mixed_session_syllabus_routing -v` | Mixed session's syllabus segment alone is routed to A6 (AC-13) |

**Test Case Details (Given/When/Then):**

**T50.1 — Syllabus lecture follows identical capture path**
- **Given:** a lecture session classified as type "syllabus" with audio input
- **When:** the session is processed through the standard capture/ASR pipeline (S19, S09)
- **Then:** the transcript is produced identically to a content lecture; only the downstream routing differs (→ A6 instead of topic extraction)

**T50.2 — Extracted items land in DB-3, not DB-2**
- **Given:** a syllabus lecture transcript processed by A6
- **When:** extraction completes successfully
- **Then:** all extracted items are present in `syllabus_items` table on PG-SYLLABUS (DB-3), and NO corresponding entries exist in DB-2 topic tables

**T50.3 — Hierarchy and ordinals correct**
- **Given:** a transcript containing "Module 1: Intro → Topic 1.1 → Topic 1.2; Module 2: Data → Topic 2.1"
- **When:** A6 extracts syllabus items
- **Then:** Module 1 has ordinal 0, Topic 1.1 has parent=Module 1 ordinal 0, Topic 1.2 has parent=Module 1 ordinal 1; Module 2 has ordinal 1; ordinals are sequential within each parent

**T50.4 — No agent other than A6 can write to DB-3**
- **Given:** a database connection with the `lis` FDW user (PG-MAIN) and a non-A6 application context
- **When:** an INSERT is attempted on `syllabus_items` via the FDW link or direct connection
- **Then:** the write is rejected with a permission error; only the `a6_writer` role can INSERT/UPDATE/DELETE on PG-SYLLABUS

**T50.5 — Extraction accuracy ≥ 0.85 on 20 real syllabi**
- **Given:** 20 real syllabus transcripts with human-annotated ground truth (item titles, hierarchy, ordinals)
- **When:** A6 extracts items from each transcript
- **Then:** F1 score (title matching + hierarchy accuracy + ordinal correctness) ≥ 0.85 across all 20 transcripts

**T50.6 — Mixed session syllabus segment routed to A6**
- **Given:** a mixed session containing both content and syllabus segments, classified by S35
- **When:** the session is processed
- **Then:** only the syllabus segment is routed to A6 for extraction; content segments are processed by the normal topic pipeline; no content-topic items appear in DB-3

**Verification Commands:**
```bash
# Full local verification
uv run pytest tests/test_a6_syllabus.py tests/test_syllabus_write_authority.py -v -k "S50 or a6_syllabus" && \
uv run mypy --strict src/agents/a6/ src/services/syllabus/ && \
uv run ruff check src/agents/a6/ src/services/syllabus/ && \
uv run pytest tests/test_a6_syllabus.py::test_extraction_accuracy_20_syllabi -v  # eval gate
```

**Exit Criteria:**
- [ ] T50.1 passes — syllabus lecture follows identical capture/ASR path
- [ ] T50.2 passes — items land in DB-3, not DB-2
- [ ] T50.3 passes — hierarchy and ordinals correct
- [ ] T50.4 passes — no agent other than A6 can write to DB-3
- [ ] T50.5 passes — extraction accuracy ≥ 0.85 on 20 real syllabi
- [ ] T50.6 passes — mixed session syllabus segment routed to A6

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- A6 write-authority is enforced at TWO levels: DB role (GRANT only to `a6_writer`) and application guard (`DB3WriteGuard`). Both must be implemented; the DB role is the hard gate, the application guard is defense-in-depth
- Grammar-constrained decoding requires model-specific grammar files — cache them to avoid recompilation on every request
- Syllabus lectures may have non-standard ASR output (less conversational, more list-like) — test with real transcripts
- Mixed-session segmentation must happen BEFORE A6 extraction; routing a full mixed transcript to A6 will produce noisy output
- Ordinals must be re-indexed after deduplication — same title appearing twice gets merged, ordinals shift

**Fallback Instructions:**
- If A6 extraction fails: log the transcript chunk, skip DB-3 write, downstream coverage shows `not_started` for all items
- If grammar compilation fails: fall back to Instructor-style validation with bounded retry (1 attempt)
- If DB-3 unavailable: cache extraction result in Redis with 24h TTL, retry write on next A6 run
- If grade of authority > 2: reject extraction, log, do not write; downstream dashboard shows "extraction pending"

**Rollback Procedure:**
- Disable A6 extraction by setting `A6_EXTRACTION_ENABLED=false` in `.env`
- Syllabus lectures will still be captured and transcribed (no data loss), but no items will be written to DB-3
- Coverage dashboard (S52) will show empty syllabus for affected subjects
- No database migration rollback needed — DB-3 schema is additive (new items)
- To purge incorrect extractions: `DELETE FROM syllabus_items WHERE source_session_id = '<session_id>'` on PG-SYLLABUS

---

### 9. Observability

**Metrics Added:**
- `a6_extraction_total`: counter of extraction attempts (labels: status=success/rejected/failed, source=lecture/upload)
- `a6_extraction_items_count`: histogram of items extracted per transcript
- `a6_extraction_confidence`: histogram of extraction_confidence scores
- `a6_extraction_latency_seconds`: histogram of end-to-end extraction latency
- `a6_write_authority_rejection_total`: counter of unauthorized write attempts (labels: caller_agent, method)
- `a6_db3_write_total`: counter of DB-3 writes (labels: status=success/error)

**Tracing/Logging:**
- Span: `a6.extract` with attributes (session_id, subject_id, transcript_length, item_count, confidence, grade_of_authority)
- Span: `a6.db3_write` with attributes (item_count, latency_ms)
- Log: INFO on successful extraction with item count and confidence
- Log: WARNING on grade of authority > 2 (low confidence rejection)
- Log: ERROR on schema validation failure with raw LLM output
- Log: ERROR on unauthorized write attempt (security event)

**Alerts:**
- Write authority rejection rate > 0 over 1 hour: potential security issue
- Extraction failure rate > 20% over 1 hour: investigate LLM output quality or schema drift
- Extraction confidence mean drops below 0.7 over 1 day: syllabus quality degrading

---

### 10. Exit Checklist

- [ ] All tests pass (T50.1, T50.2, T50.3, T50.4, T50.5, T50.6)
- [ ] A6 agent extracts structured syllabus items from transcripts
- [ ] Items written exclusively to DB-3 (PG-SYLLABUS), never to DB-2
- [ ] Write-authority enforced at both DB role and application guard levels
- [ ] Hierarchy and ordinals correct after extraction
- [ ] Mixed-session syllabus segment isolation works (AC-13)
- [ ] Extraction accuracy ≥ 0.85 on 20 real syllabus transcripts
- [ ] Observability: metrics, traces, and alerts in place
