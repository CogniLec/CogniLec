# S55 — Shared Retrieval Service
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Build a stateless `RetrievalService` over DB-1/DB-2 that serves both A3 and A5 independently, implementing hybrid recall → rerank → optional hierarchical merge with LlamaIndex vs hand-rolled SQL evaluation (D-31 decision).

**Component Boundaries:**
- **Allowed:** `src/services/retrieval/`, `src/db/queries/`, `tests/test_retrieval.py`, `tests/test_hierarchical_merge.py`, `config/retrieval.yaml`
- **Off-limits:** Agent implementations (S56, S57), Reranker service internals (S54), Embedding pipeline (S48)

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| SQLAlchemy | 2.0.52 | Async DB queries |
| pgvector | 0.3.x | Vector similarity search |
| LlamaIndex | 0.12.x | Auto-merging retriever evaluation |
| pytest | 8.x | Integration tests |
| testcontainers | 4.6.x | PostgreSQL for integration tests |

---

### 2. State Machine & Domain Schemas

**Retrieval Pipeline Flow:**
```
query → hybrid_recall (pgvector + tsvector) → candidate_pool
      → rerank (RerankerClient) → top_k
      → hierarchical_merge (optional) → final_results
```

**Retrieval Result Schema:**
```python
# src/services/retrieval/models.py
from pydantic import BaseModel, Field
from uuid import UUID

class RetrievalResult(BaseModel):
    id: UUID
    content: str
    source_type: str = Field(..., pattern="^(utterance|segment|topic|note_section)$")
    source_id: UUID
    score: float = Field(..., ge=0.0, le=1.0)
    metadata: dict = Field(default_factory=dict)
    # Hierarchical context (populated by merge)
    parent_topic_id: UUID | None = None
    parent_topic_name: str | None = None
    sibling_segments: list[str] = Field(default_factory=list)

class RetrievalResponse(BaseModel):
    results: list[RetrievalResult]
    total_candidates: int
    reranked: bool
    hierarchical_merged: bool
    latency_ms: int
    query: str

class RetrievalRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    subject_id: UUID
    source_types: list[str] = Field(
        default=["utterance", "segment", "note_section"]
    )
    top_k: int = Field(default=10, ge=1, le=50)
    rerank: bool = Field(default=True)
    hierarchical_merge: bool = Field(default=True)

# src/services/retrieval/config.py
class RetrievalConfig(BaseModel):
    db_main_url: str
    db_syllabus_url: str
    reranker_endpoint: str = "http://reranker:80"
    embedding_endpoint: str = "http://tei:80"
    default_top_k: int = 10
    max_candidates: int = 100
    enable_hierarchical_merge: bool = True
    llmama_index_comparison: bool = True  # D-31 evaluation flag
```

**RetrievalService Interface:**
```python
# src/services/retrieval/service.py
class RetrievalService:
    """Stateless retrieval service. No agent identity, no shared state."""
    
    async def retrieve(
        self, request: RetrievalRequest
    ) -> RetrievalResponse:
        """Full retrieval pipeline: hybrid recall → rerank → merge."""
        ...
    
    async def hybrid_recall(
        self, query: str, subject_id: UUID, source_types: list[str], limit: int
    ) -> list[RetrievalResult]:
        """First-stage: pgvector cosine + tsvector ts_rank via RRF."""
        ...
    
    async def hierarchical_merge(
        self, results: list[RetrievalResult], subject_id: UUID
    ) -> list[RetrievalResult]:
        """Merge utterances into topic-level context groups."""
        ...
```

**State Transition Rules:**
- Service is stateless: no session state between calls
- Identical queries return identical results regardless of caller
- Hierarchical merge groups utterances under their parent topic

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Create `src/services/retrieval/models.py` with Pydantic schemas | Import succeeds, mypy passes |
| 2 | Create `src/services/retrieval/config.py` with env-based config | Config loads from .env |
| 3 | Implement hybrid_recall using pgvector + tsvector RRF | Unit test: returns results from both sources |
| 4 | Implement hierarchical_merge for topic grouping | Unit test: utterances grouped under parent topic |
| 5 | Create RetrievalService orchestrating recall → rerank → merge | Integration test: full pipeline works |
| 6 | Add LlamaIndex auto-merging retriever comparison | Comparison test: D-31 decision recorded |
| 7 | Add statelessness assertions (no shared state) | T55.2: FR-3.7 structural assertion |
| 8 | Add subject scoping | T55.5: results never cross subject boundary |
| 9 | Add performance benchmark | T55.6: full pipeline < 1s |
| 10 | Write integration tests with testcontainers | All T55.x tests pass |

**Atomic Sub-tasks:**
1. Pydantic schemas and config for retrieval service
2. Hybrid recall implementation (pgvector + tsvector RRF)
3. Hierarchical merge implementation (utterance→segment→topic)
4. LlamaIndex vs hand-rolled comparison for D-31 decision
5. RetrievalService orchestration layer
6. Subject scoping enforcement
7. Integration and performance test suite

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| No candidates found for query | Return empty results, no error |
| Hierarchical merge finds no parent topic | Return results without topic grouping |
| LlamaIndex retriever unavailable | Fall back to hand-rolled SQL implementation |
| Query exceeds max length | Truncate to limit, log warning |
| Subject has no embeddings | Return empty results for that subject |
| Reranker unavailable | Skip reranking, proceed with first-stage results |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Strategy pattern: LlamaIndex vs hand-rolled for D-31 comparison
- Stateless service: no instance state between calls
- Dependency injection: DB connections and reranker client injected
- Pipeline pattern: recall → rerank → merge as composable steps

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase
- Files: snake_case (`retrieval_service.py`, `hierarchical_merge.py`)
- Functions: snake_case (`hybrid_recall`, `hierarchical_merge`)
- Constants: UPPER_SNAKE_CASE

**Code Splitting Metrics:**
- Max function length: 40 lines
- Max file length: 300 lines
- Max class methods: 10

**Type Safety:**
- All function signatures typed with Pydantic v2 models
- `from __future__ import annotations` in all files
- Return types explicit on all public methods
- UUID type hints for all ID parameters

---

### 5. API & Interface Contracts

**Internal API:**
```python
# src/services/retrieval/service.py
class RetrievalService:
    def __init__(
        self,
        db_main: AsyncSession,
        db_syllabus: AsyncSession,
        reranker: RerankerClient | None = None,
        config: RetrievalConfig | None = None,
    ):
        ...

    async def retrieve(self, request: RetrievalRequest) -> RetrievalResponse:
        """Full retrieval pipeline. Stateless — no shared state between callers."""
        ...

    async def hybrid_recall(
        self,
        query: str,
        subject_id: UUID,
        source_types: list[str],
        limit: int,
    ) -> list[RetrievalResult]:
        """First-stage retrieval using pgvector + tsvector RRF."""
        ...

    async def hierarchical_merge(
        self,
        results: list[RetrievalResult],
        subject_id: UUID,
    ) -> list[RetrievalResult]:
        """Group utterances under parent topic for context."""
        ...
```

**Hybrid Recall Query (SQL):**
```sql
WITH vector_results AS (
    SELECT id, content, source_type, source_id,
           1 - (embedding <=> $1) AS vector_score
    FROM utterances
    WHERE subject_id = $2
      AND source_type = ANY($3)
    ORDER BY embedding <=> $1
    LIMIT $4
),
lexical_results AS (
    SELECT id, content, source_type, source_id,
           ts_rank(search_vector, plainto_tsquery('english', $5)) AS lexical_score
    FROM utterances
    WHERE subject_id = $2
      AND source_type = ANY($3)
      AND search_vector @@ plainto_tsquery('english', $5)
    ORDER BY lexical_score DESC
    LIMIT $4
),
combined AS (
    SELECT id, content, source_type, source_id, vector_score, lexical_score,
           -- Reciprocal Rank Fusion
           (1.0 / (60 + rank())) AS rrf_vector,
           (1.0 / (60 + rank())) AS rrf_lexical
    FROM vector_results
    FULL OUTER JOIN lexical_results USING (id)
)
SELECT id, content, source_type, source_id,
       (COALESCE(rrf_vector, 0) + COALESCE(rrf_lexical, 0)) AS combined_score
FROM combined
ORDER BY combined_score DESC
LIMIT $4;
```

**Hierarchical Merge Schema:**
```python
class TopicGroup(BaseModel):
    topic_id: UUID
    topic_name: str
    segments: list[SegmentGroup]

class SegmentGroup(BaseModel):
    segment_id: UUID
    utterances: list[RetrievalResult]
```

**Mock Request/Response Payloads:**
```json
// POST /internal/retrieval (internal API, not public)
// RetrievalRequest
{
  "query": "What is gradient descent?",
  "subject_id": "550e8400-e29b-41d4-a716-446655440000",
  "source_types": ["utterance", "note_section"],
  "top_k": 5,
  "rerank": true,
  "hierarchical_merge": true
}

// RetrievalResponse
{
  "results": [
    {
      "id": "660e8400-e29b-41d4-a716-446655440001",
      "content": "Gradient descent is an optimization algorithm...",
      "source_type": "note_section",
      "source_id": "...",
      "score": 0.92,
      "metadata": {"timestamp": "2026-09-12T10:30:00Z"},
      "parent_topic_id": "...",
      "parent_topic_name": "Optimization Methods",
      "sibling_segments": ["Learning rate schedules", "Convergence criteria"]
    }
  ],
  "total_candidates": 45,
  "reranked": true,
  "hierarchical_merge": true,
  "latency_ms": 450,
  "query": "What is gradient descent?"
}
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Default |
|----------|------|-------------|---------|
| `DATABASE_URL` | string | PG-MAIN connection (asyncpg) | `postgresql+asyncpg://localhost:5432/lis` |
| `SYLLABUS_DATABASE_URL` | string | PG-SYLLABUS connection | `postgresql+asyncpg://localhost:5432/lis_syllabus` |
| `RERANKER_ENDPOINT` | string | Reranker service URL | `http://reranker:80` |
| `EMBEDDING_ENDPOINT` | string | TEI embedding endpoint | `http://tei:80` |
| `RETRIEVAL_DEFAULT_TOP_K` | int | Default results count | `10` |
| `RETRIEVAL_MAX_CANDIDATES` | int | Max first-stage candidates | `100` |
| `RETRIEVAL_HIERARCHICAL_MERGE` | bool | Enable hierarchical merge | `true` |
| `LLAMAINDEX_COMPARISON` | bool | Enable LlamaIndex vs hand-rolled eval | `true` |

**Third-Party Integration Contracts:**
- RerankerClient (S54): async HTTP client with timeout and fallback
- PG-MAIN: pgvector extension for vector search, tsvector for lexical search
- PG-SYLLABUS: read-only access for syllabus-merged queries

**Version Pins:**
- `llama-index` pinned in `pyproject.toml` for comparison evaluation
- `pgvector` pinned in Docker Compose for PG extension

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T55.1 | I | `pytest tests/test_retrieval.py::test_stateless_identical_results -v` | Same query returns identical results regardless of caller |
| T55.2 | I | `pytest tests/test_retrieval.py::test_no_agent_identity -v` | Service holds no agent identity, no shared state |
| T55.3 | V | `pytest tests/test_retrieval.py::test_hierarchical_merge -v` | Merge returns topic-level context, not disconnected utterances |
| T55.4 | V | `pytest tests/test_retrieval.py::test_llamaindex_vs_handrolled -v` | LlamaIndex vs hand-rolled measured; decision recorded |
| T55.5 | I | `pytest tests/test_retrieval.py::test_subject_scoping -v` | Results scoped to single subject |
| T55.6 | P | `pytest tests/test_retrieval.py::test_retrieval_perf -v` | Full pipeline (recall + rerank + merge) in < 1s |

**Test Case Details (Given/When/Then):**

**T55.1 — Stateless identical results**
- **Given:** a query "optimization" and subject_id "abc"
- **When:** RetrievalService.retrieve() is called twice with identical parameters
- **Then:** both calls return identical results (same IDs, scores, ordering)

**T55.2 — No agent identity**
- **Given:** RetrievalService is instantiated twice (simulating A3 and A5)
- **When:** both instances query with identical parameters
- **Then:** results are identical; no agent-specific state influences results

**T55.3 — Hierarchical merge**
- **Given:** 10 utterance results all belonging to the same topic
- **When:** hierarchical_merge() is called
- **Then:** results are grouped under parent topic with sibling segment context

**T55.4 — LlamaIndex vs hand-rolled**
- **Given:** 50 labelled queries with known relevance judgments
- **When:** both implementations run against the same query set
- **Then:** precision/recall metrics recorded; D-31 decision documented

**T55.5 — Subject scoping**
- **Given:** results exist in subject A and subject B
- **When:** retrieval is scoped to subject A
- **Then:** no results from subject B appear in output

**T55.6 — Performance benchmark**
- **Given:** a query with 100 candidates
- **When:** full pipeline (hybrid recall → rerank → hierarchical merge) runs
- **Then:** total latency is < 1s

**Verification Commands:**
```bash
# Full local verification
uv run pytest tests/test_retrieval.py -v -k "S55 or retrieval" && \
uv run mypy --strict src/services/retrieval/ && \
uv run ruff check src/services/retrieval/
```

**Exit Criteria:**
- [ ] T55.1 passes — service is stateless
- [ ] T55.2 passes — no agent identity or shared state
- [ ] T55.3 passes — hierarchical merge produces topic-level context
- [ ] T55.4 passes — LlamaIndex vs hand-rolled comparison recorded
- [ ] T55.5 passes — subject scoping enforced
- [ ] T55.6 passes — full pipeline < 1s

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- LlamaIndex auto-merging retriever may not match the exact hierarchy model (utterance→segment→topic)
- Hand-rolled SQL may outperform LlamaIndex for this specific hierarchy — measure, don't assume
- Hierarchical merge is O(n log n) for grouping; can degrade with very large result sets
- Cross-subject leakage is the #1 retrieval bug — always test with multi-subject fixtures

**Fallback Instructions:**
- If LlamaIndex comparison shows worse performance: document decision, use hand-rolled SQL
- If hierarchical merge is slow: add topic_id index on utterances table
- If reranker unavailable: skip reranking, log warning, return first-stage results
- If hybrid recall returns nothing: check embedding index is populated for the subject

**Rollback Procedure:**
- Hierarchical merge can be disabled via `RETRIEVAL_HIERARCHICAL_MERGE=false`
- LlamaIndex comparison can be disabled via `LLAMAINDEX_COMPARISON=false`
- No database migrations required
- Service removal: delete `src/services/retrieval/`, update imports

---

### 9. Observability (if applicable)

**Metrics Added:**
- `retrieval_request_total`: counter of retrieval requests (labels: status, source_types)
- `retrieval_latency_seconds`: histogram of full pipeline latency
- `retrieval_candidates_count`: histogram of first-stage candidate counts
- `retrieval_reranked_count`: histogram of reranked result counts
- `retrieval_hierarchical_merge_groups`: histogram of topic groups formed
- `retrieval_llamaindex_comparison_score`: gauge for D-31 comparison results

**Tracing/Logging:**
- Span: `retrieval.pipeline` with child spans for recall, rerank, merge
- Log: INFO on query with latency and result count
- Log: DEBUG on hierarchical merge grouping details
- Log: INFO on D-31 comparison results

**Alerts:**
- Retrieval P95 latency > 1s: investigate GPU or DB performance
- Hierarchical merge returns > 50 groups: potential over-fragmentation

---

### 10. Exit Checklist

- [ ] All tests pass (T55.1–T55.6)
- [ ] Service is stateless — identical queries return identical results
- [ ] Hierarchical merge groups utterances under parent topics
- [ ] LlamaIndex vs hand-rolled comparison completed and documented
- [ ] Subject scoping enforced — no cross-subject leakage
- [ ] Full pipeline < 1s performance met
- [ ] D-31 decision recorded with evidence
