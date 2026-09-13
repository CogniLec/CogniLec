# S52 — Coverage Mapping & Dashboard
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Align discovered topics to syllabus items by embedding similarity; persist `coverage_status` (`not_started` / `partial` / `covered`) and `covered_by` topic IDs on DB-3; provide a subject dashboard showing declared vs covered vs outstanding items. Alignment is advisory and user-correctable.

**Component Boundaries:**
- **Allowed:** `src/services/coverage/`, `src/api/routes/coverage.py`, `src/api/routes/dashboard.py`, `src/db/repositories/coverage_repo.py`, `frontend/src/components/Dashboard/`, `tests/test_coverage_mapping.py`, `tests/test_dashboard.py`
- **Off-limits:** A6 extraction (S50), syllabus upload parsing (S51), topic discovery (S28–S32), embedding generation (S48)

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| NumPy | 1.26.x | Cosine similarity computation |
| pgvector | 0.8.x | Vector similarity queries on PG-SYLLABUS |
| FastAPI | 0.115.x | Coverage and dashboard endpoints |
| SQLAlchemy | 2.0.52 | DB queries via FDW |
| pytest | 8.x | Integration tests |
| testcontainers | 4.6.x | PG-SYLLABUS + PG-MAIN for tests |

---

### 2. State Machine & Domain Schemas

**Coverage Status State Machine:**
```
not_started → partial (at least one topic aligns, but not all)
            → covered (all sub-items covered by at least one topic)
partial → covered (remaining sub-items covered by new topics)
covered → partial (topic removed or unlinked — edge case)
```

**Alignment Confidence Thresholds:**
```
cosine_similarity ≥ 0.80 → auto-aligned (high confidence)
0.60 ≤ cosine < 0.80 → suggested (user confirms/rejects)
cosine < 0.60 → not aligned (too dissimilar)
```

**Pydantic Models:**
```python
# src/services/coverage/models.py
from pydantic import BaseModel, Field
from enum import Enum


class CoverageStatus(str, Enum):
    NOT_STARTED = "not_started"
    PARTIAL = "partial"
    COVERED = "covered"


class AlignmentConfidence(str, Enum):
    AUTO = "auto"  # cosine ≥ 0.80
    SUGGESTED = "suggested"  # 0.60 ≤ cosine < 0.80
    NONE = "none"  # cosine < 0.60


class TopicSyllabusAlignment(BaseModel):
    topic_id: UUID
    syllabus_item_id: UUID
    cosine_similarity: float = Field(..., ge=0.0, le=1.0)
    confidence: AlignmentConfidence
    auto_aligned: bool  # True if auto-aligned, False if user-confirmed


class SyllabusCoverageSummary(BaseModel):
    subject_id: UUID
    total_items: int
    covered_items: int
    partial_items: int
    not_started_items: int
    coverage_pct: float = Field(..., ge=0.0, le=100.0)
    items: list[SyllabusItemCoverageDetail]


class SyllabusItemCoverageDetail(BaseModel):
    item_id: UUID
    title: str
    item_type: str
    ordinal: int
    parent_id: UUID | None
    coverage_status: CoverageStatus
    covered_by_topics: list[UUID]
    alignment_confidence: AlignmentConfidence | None = None


class AlignmentCorrection(BaseModel):
    """User correction to a topic-syllabus alignment."""

    topic_id: UUID
    syllabus_item_id: UUID
    action: str = Field(..., pattern="^(link|unlink|replace)$")
    replace_with_item_id: UUID | None = None  # only for action="replace"


class CoverageUpdateEvent(BaseModel):
    subject_id: UUID
    session_id: UUID
    new_topics: list[UUID]
    updated_items: list[UUID]
    timestamp: str
```

**State Transition Rules:**
- After each session: recompute coverage for all syllabus items in the subject
- New topic discovered → compute similarity to all uncovered syllabus items
- Auto-align if cosine ≥ 0.80; suggest if 0.60–0.80
- Coverage status updated: all sub-items covered → "covered"; some → "partial"; none → "not_started"
- User correction persists and is NOT overwritten by automated re-alignment
- Coverage computed through FDW link (S11) — reads from PG-SYLLABUS via PG-MAIN

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Create coverage computation service | Unit test: similarity scoring works |
| 2 | Implement auto-alignment logic (cosine ≥ 0.80) | Unit test: high-similarity pairs auto-aligned |
| 3 | Implement suggested alignment (0.60–0.80) | Unit test: medium-similarity pairs flagged as suggested |
| 4 | Persist `coverage_status` and `covered_by` on DB-3 | Integration test: status updates on syllabus_items |
| 5 | Create coverage query API (FDW-based) | Integration test: query returns correct coverage |
| 6 | Implement post-session coverage update hook | Integration test: new topics trigger re-alignment |
| 7 | Build subject dashboard API | Integration test: dashboard shows correct counts |
| 8 | Add user correction endpoint (link/unlink/replace) | Integration test: corrections persist and are not overwritten |
| 9 | Build frontend dashboard component | E2E test: dashboard renders with correct data |
| 10 | Run labelled eval | T52.1: alignment accuracy ≥ 0.80 |

**Atomic Sub-tasks:**
1. Cosine similarity computation service
2. Auto-alignment logic with configurable thresholds
3. Suggested alignment queue for user review
4. DB-3 coverage status persistence (via FDW update or direct PG-SYLLABUS write)
5. Post-session coverage update hook (triggered by session.complete event)
6. Coverage query API (FDW reads from PG-MAIN)
7. Subject dashboard API with aggregated stats
8. User correction endpoint (link/unlink/replace actions)
9. Frontend dashboard component
10. Labelled evaluation dataset and accuracy measurement

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| FDW link unavailable | Coverage query returns cached data (last-known), logged as stale |
| No syllabus items exist | Dashboard shows "No syllabus uploaded" with link to S51 upload |
| No topics discovered yet | Dashboard shows 0% coverage, all items "not_started" |
| Multiple topics align to same item | All linked in `covered_by` array; item status = "covered" |
| User unlinks all topics from item | Status reverts to "not_started"; next session may re-align |
| Similarity score exactly at threshold (0.80) | Auto-align (use ≥, not >) |
| FDW update to PG-SYLLABUS fails | FDW is read-only from PG-MAIN; use direct PG-SYLLABUS connection for writes |
| User correction conflicts with auto-alignment | User correction wins; auto-alignment suppressed for that pair going forward |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Service pattern: `CoverageService` orchestrates alignment computation
- Repository pattern: `CoverageRepository` for DB-3 reads/writes
- Observer pattern: post-session hook triggers coverage recomputation
- Strategy pattern: alignment thresholds configurable per subject

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase (`CoverageService`, `CoverageRepository`)
- Files: snake_case (`coverage_service.py`, `coverage_repo.py`)
- API paths: `/api/v1/subjects/{id}/coverage`, `/api/v1/subjects/{id}/dashboard`
- Status enums: snake_case values (`not_started`, `partial`, `covered`)

**Code Splitting Metrics:**
- Max function length: 40 lines
- Max file length: 300 lines
- Max class methods: 8

**Type Safety:**
- All function signatures typed with Pydantic v2 models
- `from __future__ import annotations` in all files
- Enum types for coverage status and alignment confidence

---

### 5. API & Interface Contracts

**Coverage API:**
```yaml
# GET /api/v1/subjects/{subject_id}/coverage
/api/v1/subjects/{subject_id}/coverage:
  get:
    summary: Get coverage summary for a subject
    responses:
      200:
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/SyllabusCoverageSummary'

# POST /api/v1/subjects/{subject_id}/coverage/update
/api/v1/subjects/{subject_id}/coverage/update:
  post:
    summary: Trigger coverage recomputation (typically called post-session)
    requestBody:
      content:
        application/json:
          schema:
            type: object
            properties:
              session_id:
                type: string
                format: uuid
    responses:
      202:
        description: Recomputation queued

# POST /api/v1/subjects/{subject_id}/coverage/correct
/api/v1/subjects/{subject_id}/coverage/correct:
  post:
    summary: User correction of topic-syllabus alignment
    requestBody:
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/AlignmentCorrection'
    responses:
      200:
        description: Correction applied
```

**Dashboard API:**
```yaml
# GET /api/v1/subjects/{subject_id}/dashboard
/api/v1/subjects/{subject_id}/dashboard:
  get:
    summary: Subject dashboard with coverage and session stats
    responses:
      200:
        content:
          application/json:
            schema:
              type: object
              properties:
                subject_id:
                  type: string
                  format: uuid
                subject_title:
                  type: string
                total_sessions:
                  type: integer
                total_topics:
                  type: integer
                coverage:
                  $ref: '#/components/schemas/SyllabusCoverageSummary'
                recent_sessions:
                  type: array
                  items:
                    type: object
                    properties:
                      session_id: { type: string, format: uuid }
                      date: { type: string, format: date-time }
                      topics_covered: { type: integer }
                      duration_minutes: { type: integer }
```

**Coverage Repository (FDW-based reads, direct writes):**
```python
# src/db/repositories/coverage_repo.py
class CoverageRepository:
    async def get_coverage_summary(self, subject_id: UUID) -> SyllabusCoverageSummary:
        """Read coverage via FDW from PG-MAIN (joined with local topics)."""
        ...

    async def update_item_coverage(
        self,
        item_id: UUID,
        status: CoverageStatus,
        covered_by: list[UUID],
        confidence: AlignmentConfidence,
    ) -> None:
        """Write coverage update to PG-SYLLABUS (direct connection, not FDW)."""
        ...

    async def get_suggested_alignments(self, subject_id: UUID) -> list[TopicSyllabusAlignment]:
        """Get alignments with confidence=SUGGESTED awaiting user review."""
        ...

    async def persist_user_correction(
        self, subject_id: UUID, correction: AlignmentCorrection
    ) -> None:
        """Apply user correction and suppress future auto-alignment for this pair."""
        ...
```

**Coverage Service:**
```python
# src/services/coverage/coverage_service.py
class CoverageService:
    async def recompute_coverage(self, subject_id: UUID) -> SyllabusCoverageSummary:
        """Recompute all topic-syllabus alignments for a subject.

        1. Get all syllabus items (via FDW)
        2. Get all topics for subject (from DB-2)
        3. Compute cosine similarity matrix
        4. Auto-align pairs with cosine ≥ 0.80
        5. Flag pairs with 0.60 ≤ cosine < 0.80 as suggested
        6. Update coverage_status and covered_by on DB-3
        7. Respect existing user corrections (do not overwrite)
        """
        ...

    async def post_session_update(
        self, subject_id: UUID, session_id: UUID
    ) -> SyllabusCoverageSummary:
        """Triggered after session.complete event.

        Recompute coverage with newly discovered topics from the session.
        Tighter re-clustering cadence for sessions 2–5 (S53 integration).
        """
        ...
```

**Post-Session Hook:**
```python
# src/graph/session_hooks.py (addition)
async def on_session_complete(session_id: UUID, subject_id: UUID) -> None:
    """Hook called after session processing completes.

    Triggers coverage recomputation for the subject.
    Event: session.complete → coverage.recompute
    """
    await coverage_service.post_session_update(subject_id, session_id)
```

**Event Contract:**
```json
{
  "event": "coverage.updated",
  "subject_id": "uuid",
  "session_id": "uuid",
  "items_updated": 5,
  "coverage_pct": 42.5,
  "new_auto_alignments": 3,
  "new_suggested_alignments": 2,
  "timestamp": "2026-09-12T11:00:00Z"
}
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Default |
|----------|------|-------------|---------|
| `COVERAGE_AUTO_THRESHOLD` | float | Cosine similarity threshold for auto-alignment | `0.80` |
| `COVERAGE_SUGGEST_THRESHOLD` | float | Cosine similarity threshold for suggested alignment | `0.60` |
| `COVERAGE_RECOMPUTE_ON_SESSION` | bool | Auto-recompute coverage after each session | `true` |
| `COVERAGE_CACHE_TTL_S` | int | Cache TTL for coverage queries (seconds) | `300` |
| `SYLLABUS_DATABASE_URL` | string | Direct PG-SYLLABUS connection (for writes) | `postgresql://...` |
| `DATABASE_URL` | string | PG-MAIN connection (for FDW reads) | `postgresql://...` |

**Third-Party Integration Contracts:**
- pgvector: vector cosine similarity queries on PG-SYLLABUS
- NumPy: batch cosine similarity computation
- S11 FDW link: read syllabus items from PG-MAIN
- S50 A6 extraction: source of syllabus items in DB-3
- S48 embedding pipeline: source of topic embeddings for similarity computation

**Version Pins:**
- pgvector pinned in Docker Compose
- NumPy pinned in `pyproject.toml`

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T52.1 | V | `pytest tests/test_coverage_mapping.py::test_alignment_accuracy_labelled -v` | Topic-to-syllabus alignment accuracy ≥ 0.80 on labelled data |
| T52.2 | I | `pytest tests/test_dashboard.py::test_dashboard_teached_vs_outstanding -v` | Dashboard correctly reports taught vs outstanding items (AC-14) |
| T52.3 | I | `pytest tests/test_coverage_mapping.py::test_coverage_updates_after_session -v` | Coverage updates automatically after each session |
| T52.4 | I | `pytest test_coverage_mapping.py::test_user_correction_persists -v` | User correction persists and is not overwritten by auto-alignment |
| T52.5 | I | `pytest tests/test_coverage_mapping.py::test_fdw_coverage_query -v` | Coverage query works through FDW link (S11) |

**Test Case Details (Given/When/Then):**

**T52.1 — Alignment accuracy ≥ 0.80**
- **Given:** 50 labelled topic-syllabus item pairs with known correct alignments
- **When:** `CoverageService.recompute_coverage()` runs on the labelled dataset
- **Then:** precision and recall of auto-aligned pairs (cosine ≥ 0.80) are both ≥ 0.80 compared to ground truth

**T52.2 — Dashboard reports taught vs outstanding (AC-14)**
- **Given:** a subject with 20 syllabus items, 8 covered, 5 partial, 7 not_started
- **When:** `GET /api/v1/subjects/{id}/dashboard` is called
- **Then:** response shows total_items=20, covered_items=8, partial_items=5, not_started_items=7, coverage_pct=40.0; each item has correct coverage_status

**T52.3 — Coverage updates after session**
- **Given:** a subject with 10 "not_started" syllabus items and a new session that discovers 3 topics
- **When:** the session completes and `on_session_complete` hook fires
- **Then:** coverage is recomputed; at least some of the 10 items now have status "partial" or "covered" with the new topic IDs in `covered_by`

**T52.4 — User correction persists and is not overwritten**
- **Given:** a user manually links topic T1 to syllabus item S3 (unlinking from suggested S5)
- **When:** a subsequent session triggers coverage recomputation
- **Then:** the T1→S3 link persists; auto-alignment does NOT overwrite it back to T1→S5; the user correction is marked as `auto_aligned=False`

**T52.5 — Coverage query works through FDW link**
- **Given:** syllabus items on PG-SYLLABUS and topics on PG-MAIN
- **When:** `GET /api/v1/subjects/{id}/coverage` is called
- **Then:** the query joins local topics with foreign syllabus_items via FDW and returns correct coverage data

**Verification Commands:**
```bash
# Full local verification
uv run pytest tests/test_coverage_mapping.py tests/test_dashboard.py -v -k "S52 or coverage or dashboard" && \
uv run mypy --strict src/services/coverage/ src/api/routes/coverage.py src/api/routes/dashboard.py && \
uv run ruff check src/services/coverage/ src/api/routes/coverage.py src/api/routes/dashboard.py && \
uv run pytest tests/test_coverage_mapping.py::test_alignment_accuracy_labelled -v  # eval gate
```

**Exit Criteria:**
- [ ] T52.1 passes — alignment accuracy ≥ 0.80 on labelled data
- [ ] T52.2 passes — dashboard correctly reports taught vs outstanding items (AC-14)
- [ ] T52.3 passes — coverage updates automatically after each session
- [ ] T52.4 passes — user correction persists and is not overwritten
- [ ] T52.5 passes — coverage query works through FDW link

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- FDW is READ-ONLY from PG-MAIN — coverage status writes must go through direct PG-SYLLABUS connection, not FDW
- Embedding dimension mismatch (topic embeddings vs. syllabus item embeddings) will cause similarity computation to fail — ensure both use same embedding model (S48)
- Auto-alignment threshold must be ≥ (not >) to include exact matches at the boundary
- User corrections must be stored separately from auto-alignment results to prevent overwrite during recomputation
- Coverage computation can be expensive for subjects with many items × many topics — consider batch processing and caching

**Fallback Instructions:**
- If FDW link unavailable: serve cached coverage data (last-known), log as stale, recompute when FDW recovers
- If embedding similarity computation fails: fall back to title-based keyword matching (lower accuracy but functional)
- If coverage recomputation times out (> 30s): queue for background processing, return partial results
- If PG-SYLLABUS unavailable for writes: queue coverage updates, retry on next session

**Rollback Procedure:**
- Disable auto-recompute: set `COVERAGE_RECOMPUTE_ON_SESSION=false` in `.env`
- Coverage data remains in DB-3; dashboard still shows last-known state
- No database migration rollback needed — coverage columns are additive
- To clear all coverage data: `UPDATE syllabus_items SET coverage_status = 'not_started', covered_by = '{}' WHERE subject_id = '<id>'`

---

### 9. Observability

**Metrics Added:**
- `coverage_recompute_total`: counter of recomputation triggers (labels: trigger=session/user/manual)
- `coverage_recompute_duration_seconds`: histogram of recomputation latency
- `coverage_alignment_auto_total`: counter of auto-aligned pairs (per session)
- `coverage_alignment_suggested_total`: counter of suggested pairs (per session)
- `coverage_user_correction_total`: counter of user corrections (labels: action=link/unlink/replace)
- `coverage_fdw_query_duration_seconds`: histogram of FDW query latency
- `coverage_fdw_error_total`: counter of FDW query failures

**Tracing/Logging:**
- Span: `coverage.recompute` with attributes (subject_id, item_count, topic_count, latency_ms)
- Span: `coverage.align` with attributes (pair_count, auto_count, suggested_count)
- Span: `coverage.dashboard` with attributes (subject_id, latency_ms)
- Log: INFO on recompute completion with alignment counts
- Log: WARNING on FDW query failure (serving cached data)
- Log: INFO on user correction applied

**Alerts:**
- FDW error rate > 5% over 5 minutes: investigate PG-SYLLABUS availability
- Coverage recomputation P95 > 30s: check embedding similarity computation performance
- Auto-alignment accuracy drops below 0.70 over 1 week: investigate embedding model drift

---

### 10. Exit Checklist

- [ ] All tests pass (T52.1, T52.2, T52.3, T52.4, T52.5)
- [ ] Alignment accuracy ≥ 0.80 on labelled data
- [ ] Dashboard shows correct taught vs outstanding items (AC-14)
- [ ] Coverage updates automatically after each session
- [ ] User corrections persist and are not overwritten
- [ ] FDW link works for coverage queries
- [ ] Coverage writes go directly to PG-SYLLABUS (not via FDW)
- [ ] Frontend dashboard renders correctly
- [ ] Observability: metrics, traces, and alerts in place
