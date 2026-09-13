# S54 — Reranker Service
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Deploy Qwen3-Reranker alongside TEI and build a two-stage retrieval helper that always reranks candidates — improving precision@5 over first-stage-only retrieval for A3 and A5 agents.

**Component Boundaries:**
- **Allowed:** `src/services/reranker/`, `src/services/retrieval/reranker.py`, `tests/test_reranker.py`, `config/reranker.yaml`, Docker Compose additions for reranker service
- **Off-limits:** RetrievalService implementation (S55), agent implementations (S56, S57), embedding pipeline (S48)

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| Qwen3-Reranker | latest via TEI | Cross-encoder reranking model |
| text-embeddings-inference | 1.x | Model serving infrastructure |
| sentence-transformers | 3.x | Reranker client / scoring |
| pytest | 8.x | Integration tests |
| testcontainers | 4.6.x | Container orchestration for tests |

---

### 2. State Machine & Domain Schemas

**Reranker Scoring Flow:**
```
candidates_in → cross_encoder_score → scored_candidates_out
                                      (ascending relevance score)
```

**Reranker Request/Response Schemas:**
```python
# src/services/reranker/models.py
from pydantic import BaseModel, Field


class RerankerRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    documents: list[str] = Field(..., min_length=1, max_length=100)


class RerankerResult(BaseModel):
    index: int = Field(..., ge=0)
    score: float = Field(..., ge=-1.0, le=1.0)
    document: str


class RerankerResponse(BaseModel):
    results: list[RerankerResult]
    latency_ms: int = Field(..., ge=0)


# src/services/reranker/config.py
class RerankerConfig(BaseModel):
    model_name: str = "Qwen/Qwen3-Reranker"
    endpoint: str = "http://reranker:8080"
    timeout_ms: int = 5000
    max_batch_size: int = 50
    enabled: bool = True  # feature flag for graceful degradation
```

**State Transition Rules:**
- Reranker available: always-on — no cost gating per v2.0 §3.4
- Reranker unavailable: pipeline falls back to first-stage results with warning log
- Request size > max_batch_size: split into batches, merge results

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Add Qwen3-Reranker to Docker Compose alongside TEI | Container starts and health check passes |
| 2 | Create `src/services/reranker/__init__.py` with config loading | Import succeeds, config loads from env |
| 3 | Implement `RerankerClient` with async HTTP | Unit test: mock server returns scores |
| 4 | Implement `two_stage_retrieve()` helper | Unit test: vector recall → rerank pipeline |
| 5 | Add graceful degradation on connection failure | Integration test: reranker down → results still returned |
| 6 | Add performance benchmark test | T54.3: 50 candidates reranked in < 500ms |
| 7 | Write integration tests with real reranker container | T54.1, T54.4 pass |

**Atomic Sub-tasks:**
1. Docker Compose configuration for reranker service
2. Reranker client with async HTTP and timeout handling
3. Two-stage retrieval helper (recall + rerank)
4. Graceful degradation logic (reranker unavailable → use first-stage)
5. Integration and performance test suite

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| Reranker service unavailable | Log warning, return first-stage results unchanged |
| Reranker timeout (> 5000ms) | Treat as unavailable, use first-stage results |
| Empty candidate set | Return empty list, no reranking attempted |
| Single candidate | Skip reranking, return the candidate with score 1.0 |
| Document exceeds max length | Truncate to model's max token limit, log truncation |
| Batch size exceeds max | Split into batches, merge scored results by original index |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Client pattern: `RerankerClient` wraps HTTP calls with retry and timeout
- Fallback pattern: first-stage results always available as fallback
- Factory pattern: `create_reranker_client()` for dependency injection

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase
- Files: snake_case (`reranker_client.py`)
- Functions: snake_case (`score_candidates`, `two_stage_retrieve`)
- Constants: UPPER_SNAKE_CASE

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

**Internal API:**
```python
# src/services/reranker/client.py
class RerankerClient:
    async def score(self, query: str, documents: list[str]) -> RerankerResponse:
        """Score documents against query. Returns sorted by relevance."""
        ...

    async def health_check(self) -> bool:
        """Check if reranker service is reachable."""
        ...


# src/services/retrieval/reranker.py
async def two_stage_retrieve(
    query: str,
    candidate_pool: list[str],  # first-stage results
    reranker: RerankerClient,
    top_k: int = 5,
) -> list[RerankerResult]:
    """Vector/hybrid recall then cross-encoder rerank."""
    ...
```

**Docker Compose Addition:**
```yaml
# docker-compose.override.yaml
services:
  reranker:
    image: ghcr.io/huggingface/text-embeddings-inference:latest
    command: --model-id Qwen/Qwen3-Reranker
    ports:
      - "8081:80"
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:80/health"]
      interval: 30s
      timeout: 10s
      retries: 3
```

**Mock Request/Response Payloads:**
```json
// RerankerRequest
{
  "query": "What is gradient descent?",
  "documents": [
    "Gradient descent is an optimization algorithm...",
    "The lecture covered linear algebra basics...",
    "Stochastic gradient descent updates weights..."
  ]
}

// RerankerResponse
{
  "results": [
    {"index": 0, "score": 0.92, "document": "Gradient descent is an optimization algorithm..."},
    {"index": 2, "score": 0.85, "document": "Stochastic gradient descent updates weights..."},
    {"index": 1, "score": 0.31, "document": "The lecture covered linear algebra basics..."}
  ],
  "latency_ms": 145
}
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Default |
|----------|------|-------------|---------|
| `RERANKER_ENDPOINT` | string | Reranker service URL | `http://reranker:80` |
| `RERANKER_MODEL` | string | Reranker model ID | `Qwen/Qwen3-Reranker` |
| `RERANKER_TIMEOUT_MS` | int | Request timeout in milliseconds | `5000` |
| `RERANKER_MAX_BATCH` | int | Max documents per batch | `50` |
| `RERANKER_ENABLED` | bool | Feature flag for graceful degradation | `true` |

**Third-Party Integration Contracts:**
- Qwen3-Reranker via TEI: OpenAI-compatible embeddings endpoint for scoring
- No external API dependencies; all local model serving

**Version Pins:**
- `text-embeddings-inference` pinned in Docker Compose
- `sentence-transformers` pinned in `pyproject.toml`

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T54.1 | I | `pytest tests/test_reranker.py::test_reranker_scores_candidates -v` | Reranker returns non-empty scores for all candidates |
| T54.2 | V | `pytest tests/test_reranker.py::test_reranking_improves_precision -v` | Reranked top-5 has higher precision than first-stage-only |
| T54.3 | P | `pytest tests/test_reranker.py::test_reranker_perf_50_candidates -v` | 50 candidates reranked in < 500ms |
| T54.4 | I | `pytest tests/test_reranker.py::test_reranker_unavailable_fallback -v` | Reranker down → first-stage results returned unchanged |

**Test Case Details (Given/When/Then):**

**T54.1 — Reranker returns scores**
- **Given:** a query "What is gradient descent?" and 5 candidate documents
- **When:** `RerankerClient.score(query, documents)` is called
- **Then:** response contains 5 results with scores between -1.0 and 1.0, sorted descending

**T54.2 — Reranking improves precision**
- **Given:** 50 labelled query-document pairs with known relevance
- **When:** retrieval pipeline runs with and without reranking
- **Then:** reranked precision@5 > first-stage precision@5 on the labelled set

**T54.3 — Performance benchmark**
- **Given:** 50 candidate documents and a query
- **When:** `RerankerClient.score()` is called
- **Then:** response latency is < 500ms

**T54.4 — Graceful degradation**
- **Given:** reranker service is stopped (unhealthy)
- **When:** `two_stage_retrieve()` is called with candidates
- **Then:** first-stage results are returned unchanged, warning logged

**Verification Commands:**
```bash
# Full local verification
docker compose up -d reranker && \
uv run pytest tests/test_reranker.py -v -k "S54 or reranker" && \
uv run mypy --strict src/services/reranker/ && \
uv run ruff check src/services/reranker/
```

**Exit Criteria:**
- [ ] T54.1 passes — reranker scores candidates correctly
- [ ] T54.2 passes — reranking improves precision@5 on labelled set
- [ ] T54.3 passes — 50 candidates reranked in < 500ms
- [ ] T54.4 passes — reranker unavailable does not break pipeline

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- Qwen3-Reranker requires GPU; CPU inference is too slow for real-time use
- TEI health check must be configured correctly; false positives cause intermittent failures
- Document length exceeding model max tokens causes silent truncation — add explicit truncation with warning

**Fallback Instructions:**
- If reranker fails to start: ensure GPU allocation in Docker Compose, check VRAM availability
- If reranker returns empty scores: check document encoding, log raw response for debugging
- If latency exceeds 500ms: reduce batch size, check GPU utilization

**Rollback Procedure:**
- Set `RERANKER_ENABLED=false` in `.env` to disable reranking entirely
- Remove reranker container: `docker compose stop reranker`
- Two-stage retrieval helper gracefully degrades without code changes
- No database migrations required — no rollback needed

---

### 9. Observability (if applicable)

**Metrics Added:**
- `reranker_request_total`: counter of reranker requests (labels: status=success/error/fallback)
- `reranker_latency_seconds`: histogram of reranker request latency
- `reranker_candidates_count`: histogram of candidate set sizes
- `reranker_fallback_total`: counter of fallback events (reranker unavailable)

**Tracing/Logging:**
- Span: `reranker.score` with attributes (query_length, num_documents, latency_ms)
- Log: WARNING on fallback to first-stage results
- Log: INFO on successful rerank with latency and score distribution

**Alerts:**
- Reranker fallback rate > 10% over 5 minutes: investigate reranker health
- Reranker P95 latency > 500ms: check GPU utilization

---

### 10. Exit Checklist

- [ ] All tests pass (T54.1, T54.2, T54.3, T54.4)
- [ ] Reranker Docker Compose service starts and passes health check
- [ ] Graceful degradation works when reranker is unavailable
- [ ] Performance: 50 candidates reranked in < 500ms
- [ ] Precision improvement validated on labelled query set
