# S48 — Hybrid Search
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Add generated `tsvector` columns with GIN indexes to `utterances` and `note_sections`, implement hybrid retrieval fusing lexical `ts_rank` and pgvector cosine via Reciprocal Rank Fusion, and deliver a search API with client-side search UI scoped to a subject.

**Component Boundaries:**
- **Allowed:** `src/services/search/`, `src/models/`, `src/api/search.py`, `src/ui/search/`, `tests/test_hybrid_search.py`, `tests/test_search_api.py`, Alembic migrations
- **Off-limits:** RetrievalService internals (S55), agent implementations (S56, S57), embedding pipeline modifications, Block 9–13 code

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| PostgreSQL | 15.x | tsvector columns, GIN indexes, pgvector cosine similarity |
| pgvector | 0.7.x | Vector similarity search |
| pytest | 8.x | Integration and end-to-end tests |
| testcontainers | 4.6.x | Container orchestration for tests |
| FastAPI | 0.115.x | Search API endpoint |

---

### 2. State Machine & Domain Schemas

**Search Retrieval Flow:**
```
query → parse_query → [lexical_search (tsvector + ts_rank), vector_search (pgvector cosine)]
                    → RRF fusion (k=60) → ranked_results → return top_k
```

**Database Schema Extensions:**
```sql
-- Add tsvector columns to utterances
ALTER TABLE utterances
  ADD COLUMN tsv tsvector;

CREATE INDEX idx_utterances_tsv ON utterances USING GIN(tsv);

-- Populate tsvector from transcript_text
UPDATE utterances SET tsv = to_tsvector('english', transcript_text);

-- Add tsvector columns to note_sections
ALTER TABLE note_sections
  ADD COLUMN tsv tsvector;

CREATE INDEX idx_note_sections_tsv ON note_sections USING GIN(tsv);

-- Populate tsvector from section content
UPDATE note_sections SET tsv = to_tsvector('english', content);
```

**Reciprocal Rank Fusion (RRF) Algorithm:**
```python
# src/services/search/rrf.py
def reciprocal_rank_fusion(
    lexical_results: list[dict],
    vector_results: list[dict],
    k: int = 60,
) -> list[dict]:
    """
    Fuse lexical and vector results using RRF.

    RRF score = sum(1 / (k + rank_i)) for each result across lists.
    k=60 is the standard constant from the original RRF paper.
    """
    scores: dict[str, float] = {}
    items: dict[str, dict] = {}

    for rank, result in enumerate(lexical_results):
        doc_id = result["id"]
        scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
        items[doc_id] = result

    for rank, result in enumerate(vector_results):
        doc_id = result["id"]
        scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
        if doc_id not in items:
            items[doc_id] = result

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [{"id": doc_id, "rrf_score": score, **items[doc_id]} for doc_id, score in ranked]
```

**Search Query Schema:**
```python
# src/services/search/models.py
from pydantic import BaseModel, Field


class SearchQuery(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    subject_id: str
    top_k: int = Field(default=10, ge=1, le=100)
    search_type: str = Field(default="hybrid")  # "hybrid" | "lexical" | "vector"
    source_filter: str | None = None  # "transcript" | "notes" | None (both)


class SearchResult(BaseModel):
    id: str
    source_type: str  # "utterance" | "note_section"
    content: str
    rrf_score: float
    lexical_rank: int | None = None
    vector_rank: int | None = None
    lexical_score: float | None = None
    vector_score: float | None = None
    timestamp_start: float | None = None
    timestamp_end: float | None = None


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]
    total: int
    latency_ms: int
```

**State Transition Rules:**
- Insert utterance/note_section: trigger tsvector update via DB trigger
- Update utterance/note_section: trigger tsvector re-update
- Search query: execute lexical and/or vector search based on search_type, fuse via RRF
- Subject isolation: all searches filtered by subject_id at DB level

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Create Alembic migration to add tsvector columns and GIN indexes | Migration runs successfully, indexes created |
| 2 | Add DB triggers to auto-populate tsvector on INSERT/UPDATE | T48.1: exact phrase search returns correct utterance |
| 3 | Implement `lexical_search()` in `src/services/search/lexical.py` | Unit test: ts_rank returns ranked results |
| 4 | Implement `vector_search()` in `src/services/search/vector.py` | Unit test: pgvector cosine returns ranked results |
| 5 | Implement `reciprocal_rank_fusion()` in `src/services/search/rrf.py` | Unit test: RRF merges and ranks correctly |
| 6 | Implement `hybrid_search()` in `src/services/search/hybrid.py` | T48.3: hybrid outperforms vector-only and lexical-only |
| 7 | Add search API endpoint in `src/api/search.py` | T48.5: API returns in < 300ms P95 |
| 8 | Add subject boundary enforcement | T48.4: search never crosses subject boundaries |
| 9 | Add source filter (transcript vs notes) | T48.6: search covers both transcripts and notes |
| 10 | Write client-side search UI in `src/ui/search/` | UI renders search results with relevance scores |

**Atomic Sub-tasks:**
1. Alembic migration for tsvector columns and GIN indexes
2. Database triggers for auto-populating tsvector
3. Lexical search implementation with ts_rank
4. Vector search implementation with pgvector cosine
5. RRF fusion algorithm
6. Hybrid search orchestrator
7. Search API endpoint with subject scoping
8. Client-side search UI

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| Exact phrase not in lexeme dictionary | Fall back to LIKE search with ranking, log warning |
| Empty result set from one modality | Use results from the other modality only |
| Query exceeds max length | Truncate to 500 chars, log warning |
| Vector index not ready | Fall back to lexical-only search |
| Subject boundary violation attempt | Return empty results, log security event |
| tsvector column not populated | Auto-populate on first search, log info |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Strategy pattern: `lexical_search()`, `vector_search()`, `hybrid_search()` as interchangeable strategies
- Pipeline pattern: query → parse → search → fuse → rank → return
- Repository pattern: `SearchRepository` wraps DB queries

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase
- Files: snake_case (`hybrid.py`, `rrf.py`, `lexical.py`)
- Functions: snake_case (`hybrid_search`, `reciprocal_rank_fusion`)
- Constants: UPPER_SNAKE_CASE (`RRF_K`, `MAX_QUERY_LENGTH`)

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

**Search API Endpoint:**
```yaml
# POST /api/v1/search
summary: Hybrid search across transcripts and notes
tags: [search]
requestBody:
  required: true
  content:
    application/json:
      schema:
        type: object
        required: [query, subject_id]
        properties:
          query:
            type: string
            minLength: 1
            maxLength: 500
          subject_id:
            type: string
          top_k:
            type: integer
            default: 10
            minimum: 1
            maximum: 100
          search_type:
            type: string
            enum: [hybrid, lexical, vector]
            default: hybrid
          source_filter:
            type: string
            enum: [transcript, notes]
            nullable: true
responses:
  200:
    description: Search results
    content:
      application/json:
        schema:
          type: object
          properties:
            query:
              type: string
            results:
              type: array
              items:
                type: object
                properties:
                  id: { type: string }
                  source_type: { type: string, enum: [utterance, note_section] }
                  content: { type: string }
                  rrf_score: { type: number }
                  lexical_rank: { type: integer, nullable: true }
                  vector_rank: { type: integer, nullable: true }
                  timestamp_start: { type: number, nullable: true }
                  timestamp_end: { type: number, nullable: true }
            total: { type: integer }
            latency_ms: { type: integer }
  400:
    description: Invalid query parameters
  403:
    description: Subject boundary violation
```

**Mock Request/Response Payloads:**
```json
// Request
{
  "query": "this will be on the exam",
  "subject_id": "subj_xyz789",
  "top_k": 5,
  "search_type": "hybrid",
  "source_filter": null
}

// Response
{
  "query": "this will be on the exam",
  "results": [
    {
      "id": "utt_abc123",
      "source_type": "utterance",
      "content": "This will be on the exam, so make sure you understand the concept well.",
      "rrf_score": 0.0325,
      "lexical_rank": 1,
      "vector_rank": 3,
      "lexical_score": 0.89,
      "vector_score": 0.72,
      "timestamp_start": 1234.5,
      "timestamp_end": 1238.2
    }
  ],
  "total": 1,
  "latency_ms": 142
}
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Default |
|----------|------|-------------|---------|
| `SEARCH_RRF_K` | int | RRF fusion constant | `60` |
| `SEARCH_MAX_RESULTS` | int | Max results per search | `100` |
| `SEARCH_LEXICAL_WEIGHT` | float | Weight for lexical results (1.0 = equal) | `1.0` |
| `SEARCH_VECTOR_WEIGHT` | float | Weight for vector results (1.0 = equal) | `1.0` |
| `PGVECTOR_INDEX_lists` | int | HNSW lists parameter for vector index | `100` |
| `PGVECTOR_INDEX_probes` | int | HNSW probes parameter for search | `10` |

**Third-Party Integration Contracts:**
- PostgreSQL with pgvector extension: vector similarity search and tsvector full-text search
- No external API dependencies; all local database operations

**Version Pins:**
- `pgvector` extension version pinned in Docker Compose
- PostgreSQL version pinned in Docker Compose
- `asyncpg` pinned in `pyproject.toml`

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T48.1 | I | `pytest tests/test_hybrid_search.py::test_exact_phrase_returns_correct_utterance -v` | Exact phrase "this will be on the exam" returns correct utterance |
| T48.2 | I | `pytest tests/test_hybrid_search.py::test_conceptual_query_returns_semantic_results -v` | Conceptual query returns semantically correct results |
| T48.3 | V | `pytest tests/test_hybrid_search.py::test_hybrid_outperforms_single_modality -v` | Hybrid outperforms vector-only and lexical-only on 50-query set |
| T48.4 | I | `pytest tests/test_hybrid_search.py::test_search_never_crosses_subject_boundary -v` | Search results never contain items from other subjects |
| T48.5 | P | `pytest tests/test_hybrid_search.py::test_hybrid_query_latency_p95 -v` | Hybrid query returns in < 300ms P95 |
| T48.6 | I | `pytest tests/test_hybrid_search.py::test_search_covers_transcripts_and_notes -v` | Search returns results from both transcripts and notes |

**Test Case Details (Given/When/Then):**

**T48.1 — Exact phrase search**
- **Given:** a transcript containing the utterance "This will be on the exam, so make sure you understand the concept well"
- **When:** search query `"this will be on the exam"` is executed with `search_type="lexical"`
- **Then:** the exact utterance is returned as the top result with lexical_rank=1

**T48.2 — Conceptual query**
- **Given:** transcripts and notes about reaction rates in chemistry
- **When:** search query `"the thing about reaction rates"` is executed with `search_type="hybrid"`
- **Then:** semantically relevant results about reaction rates are returned, ranked by relevance

**T48.3 — Hybrid outperforms single modality**
- **Given:** 50 labelled query-document pairs with known relevance scores
- **When:** search is run with hybrid, vector-only, and lexical-only modes
- **Then:** hybrid precision@10 > vector-only precision@10 AND hybrid precision@10 > lexical-only precision@10

**T48.4 — Subject boundary enforcement**
- **Given:** transcripts and notes from two different subjects (Subject A and Subject B)
- **When:** search query is executed with `subject_id="subj_A"`
- **Then:** all results belong to Subject A; no results from Subject B are returned

**T48.5 — Performance benchmark**
- **Given:** 1000 utterances and 200 note_sections indexed in the database
- **When:** 50 hybrid search queries are executed
- **Then:** P95 latency is < 300ms

**T48.6 — Search covers transcripts and notes**
- **Given:** utterances with "gradient descent" in transcript and note_sections with "gradient descent" in content
- **When:** search query `"gradient descent"` is executed with `source_filter=null`
- **Then:** results include both utterances and note_sections

**Verification Commands:**
```bash
# Full local verification
docker compose up -d postgres && \
uv run alembic upgrade head && \
uv run pytest tests/test_hybrid_search.py tests/test_search_api.py -v -k "S48" && \
uv run mypy --strict src/services/search/ src/api/search.py && \
uv run ruff check src/services/search/ src/api/search.py/
```

**Exit Criteria:**
- [ ] T48.1 passes — exact phrase search returns correct utterance
- [ ] T48.2 passes — conceptual query returns semantically correct results
- [ ] T48.3 passes — hybrid outperforms both vector-only and lexical-only
- [ ] T48.4 passes — search never crosses subject boundaries
- [ ] T48.5 passes — hybrid query returns in < 300ms P95
- [ ] T48.6 passes — search covers both transcripts and notes

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- tsvector columns must be populated via triggers; manual UPDATE on existing rows is required for backfill
- GIN indexes can be slow to build on large tables; schedule during maintenance window
- pgvector HNSW index requires `lists` and `probes` tuning; wrong values cause poor recall or slow queries
- RRF constant k=60 is empirical; adjust if fusion ranking is suboptimal
- ts_rank normalizes scores differently from pgvector cosine; RRF fuses ranks, not raw scores
- Subject boundary enforcement must be in WHERE clause, not application layer; DB-level enforcement is mandatory

**Fallback Instructions:**
- If tsvector column is not populated: run backfill migration `UPDATE utterances SET tsv = to_tsvector('english', transcript_text)`
- If GIN index is not created: run `CREATE INDEX idx_utterances_tsv ON utterances USING GIN(tsv)`
- If vector search fails: fall back to lexical-only search, log warning
- If lexical search fails: fall back to vector-only search, log warning
- If RRF fusion produces unexpected results: check k constant, verify both result lists are non-empty

**Rollback Procedure:**
- Drop tsvector columns: `ALTER TABLE utterances DROP COLUMN tsv; ALTER TABLE note_sections DROP COLUMN tsv;`
- Drop GIN indexes: `DROP INDEX idx_utterances_tsv; DROP INDEX idx_note_sections_tsv;`
- Revert code changes: `git revert HEAD`
- Remove search API endpoint: comment out route in `src/api/search.py`
- Feature flag: disable hybrid search via `SEARCH_HYBRID_ENABLED=false` (if implemented)

---

### 9. Observability (if applicable)

**Metrics Added:**
- `search_request_total`: counter of search requests (labels: search_type, status)
- `search_latency_seconds`: histogram of search request latency
- `search_results_count`: histogram of result set sizes
- `search_lexical_latency_seconds`: histogram of lexical search latency
- `search_vector_latency_seconds`: histogram of vector search latency
- `search_rrf_fusion_latency_seconds`: histogram of RRF fusion latency
- `search_subject_boundary_violation_total`: counter of boundary violations (security metric)

**Tracing/Logging:**
- Span: `search.query` with attributes (query_length, subject_id, search_type, top_k)
- Span: `search.lexical` nested under search.query (num_results, latency_ms)
- Span: `search.vector` nested under search.query (num_results, latency_ms)
- Span: `search.rrf_fusion` nested under search.query (num_candidates, latency_ms)
- Log: INFO on search completion with result count and latency
- Log: WARNING on subject boundary violation attempt
- Log: ERROR on search failure with query and error details

**Alerts:**
- Search P95 latency > 300ms: investigate index health or query complexity
- Subject boundary violation rate > 0: security alert, investigate
- Search error rate > 1% over 5 minutes: investigate DB or index health

---

### 10. Exit Checklist

- [ ] All tests pass (T48.1, T48.2, T48.3, T48.4, T48.5, T48.6)
- [ ] tsvector columns and GIN indexes created and populated
- [ ] Database triggers auto-populate tsvector on INSERT/UPDATE
- [ ] RRF fusion correctly merges lexical and vector results
- [ ] Search API returns results in < 300ms P95
- [ ] Subject boundary enforcement works at DB level
- [ ] Search covers both transcripts and notes
- [ ] Users can find content by remembered wording as well as by meaning
