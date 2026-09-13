# S25 — Embedding Service & Version Governance
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Deploy a TEI-based embedding service serving Qwen3-Embedding-0.6B at frozen 1024 dimensions, with model version governance that stamps every write and filters every retrieval on the active version.

**Component Boundaries:**
- **Allowed:** `config/models.yaml`, `src/services/embedding/`, `src/db/repositories/`, Docker Compose for TEI, `tests/test_embedding_service.py`
- **Off-limits:** Context-window embedding (S26), segmentation (S28), clustering (S30), prompt versioning (S40)

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| TEI (text-embeddings-inference) | 1.x | GPU embedding serving |
| sentence-transformers | 3.2.x | Fallback CPU embedding |
| Qwen3-Embedding-0.6B | frozen | 1024-dim model, only model fitting 4GB VRAM |
| pgvector | 0.5.0 | Vector storage and retrieval |
| SQLAlchemy | 2.0.52 | ORM for version registry |

---

### 2. State Machine & Domain Schemas

**Model Version State:**
```
REGISTERED → ACTIVE → DEPRECATED → RETIRED
              ↓
           BACKFILLING → ACTIVE (new version)
```

**Pydantic Models:**
```python
# src/services/embedding/config.py
from pydantic import BaseModel, Field
from enum import Enum


class EmbeddingTaskMode(str, Enum):
    RETRIEVAL = "retrieval"
    CLUSTERING = "clustering"


class EmbeddingConfig(BaseModel):
    model_name: str = "Qwen/Qwen3-Embedding-0.6B"
    dim: int = 1024
    device: str = "cuda"
    batch_size: int = 32
    tei_endpoint: str = "http://tei:8080"
    task_modes: dict[str, str] = {
        "retrieval": "Represent this sentence for searching relevant passages",
        "clustering": "Cluster this text with similar educational content",
    }


class ModelVersion(BaseModel):
    version_id: str  # e.g., "qwen3-0.6b-v1"
    model_name: str
    dim: int
    status: str  # registered, active, deprecated, retired, backfilling
    instruction_prefix: str | None = None
    created_at: datetime
    activated_at: datetime | None = None
```

**Model Registry (config/models.yaml):**
```yaml
embedding:
  active_version: "qwen3-0.6b-v1"
  versions:
    qwen3-0.6b-v1:
      model: "Qwen/Qwen3-Embedding-0.6B"
      dim: 1024
      revision: "main"
      instruction_prefixes:
        retrieval: "Represent this sentence for searching relevant passages"
        clustering: "Cluster this text with similar educational content"
      status: active
      activated_at: "2026-09-01T00:00:00Z"
```

**Version Registry Table (SQL):**
```sql
CREATE TABLE embedding_model_versions (
    version_id      VARCHAR(50) PRIMARY KEY,
    model_name      VARCHAR(100) NOT NULL,
    dim             INTEGER NOT NULL DEFAULT 1024,
    status          VARCHAR(20) NOT NULL DEFAULT 'registered',
    instruction_prefix TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    activated_at    TIMESTAMPTZ,
    deprecated_at   TIMESTAMPTZ
);

CREATE TABLE embedding_backfill_jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    from_version    VARCHAR(50) NOT NULL,
    to_version      VARCHAR(50) NOT NULL,
    subject_id      UUID NOT NULL,
    total_sessions  INTEGER NOT NULL,
    completed_sessions INTEGER NOT NULL DEFAULT 0,
    status          VARCHAR(20) NOT NULL DEFAULT 'pending',
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    UNIQUE (from_version, to_version, subject_id)
);
```

**State Transition Rules:**
- REGISTERED → ACTIVE: version activated; all new writes stamp this version
- ACTIVE → DEPRECATED: new version activated; old version no longer written
- DEPRECATED → RETIRED: backfill complete; old embeddings can be dropped
- ACTIVE → BACKFILLING: new version activated; old version backfilling in progress

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Add TEI service to Docker Compose with GPU reservation | Container starts, `curl http://tei:8080/health` returns 200 |
| 2 | Create `embedding_model_versions` and `embedding_backfill_jobs` tables | Migration succeeds |
| 3 | Implement `EmbeddingClient` wrapping TEI endpoint with fallback | Client connects and returns vectors |
| 4 | Implement `EmbeddingVersionRegistry` for version CRUD | Version operations succeed |
| 5 | Enforce `embed_model_ver` stamp on every utterance write | T25.2 passes |
| 6 | Implement retrieval filter on active version only | T25.3 passes |
| 7 | Implement backfill flow skeleton | T25.4 passes |
| 8 | Apply instruction prefix for task modes | T25.6 passes |
| 9 | Run performance benchmark | T25.5 passes |

**Atomic Sub-tasks:**
1. TEI service deployment with GPU allocation
2. `EmbeddingClient` with TEI HTTP wrapper and sentence-transformers fallback
3. Version registry CRUD operations
4. `embed_model_ver` stamp enforcement on utterance writes
5. Active-version filter on vector retrieval queries
6. Backfill flow skeleton (resumable, per-subject)
7. Instruction prefix routing for clustering vs retrieval modes

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| TEI service unavailable | Fallback to sentence-transformers local; log warning |
| Write without `embed_model_ver` | Reject with `ValueError`; DB NOT NULL constraint as guard |
| Two versions both marked active | Reject; only one active at a time enforced by registry |
| Backfill interrupted | Resume from last completed session; idempotent re-embed |
| Dimension mismatch | Validate vector length == 1024 before DB insert |
| Instruction prefix not applied | Log warning; use default (retrieval) prefix |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Client pattern: `EmbeddingClient` wraps HTTP calls with retry/fallback
- Registry pattern: single source of truth for model versions in `config/models.yaml` + DB table
- Stamp pattern: every write carries `embed_model_ver` as immutable metadata

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase
- Files: snake_case (`embedding_client.py`, `version_registry.py`)
- Constants: UPPER_SNAKE_CASE

**Code Splitting Metrics:**
- Max function length: 40 lines
- Max file length: 300 lines

**Type Safety:**
- All function signatures typed with Pydantic v2 models
- `from __future__ import annotations` in all files

---

### 5. API & Interface Contracts

**EmbeddingClient Interface:**
```python
# src/services/embedding/client.py
class EmbeddingClient:
    async def embed(
        self,
        texts: list[str],
        task_mode: EmbeddingTaskMode = EmbeddingTaskMode.RETRIEVAL,
    ) -> list[list[float]]:
        """Embed texts using TEI with task-mode instruction prefix."""

    async def embed_single(
        self,
        text: str,
        task_mode: EmbeddingTaskMode = EmbeddingTaskMode.RETRIEVAL,
    ) -> list[float]:
        """Embed a single text."""
```

**TEI Endpoint:**
```yaml
POST http://tei:8080/embed
Content-Type: application/json

Request:
  inputs:
    - "Represent this sentence for searching relevant passages: Today we will cover photosynthesis"
  parameters:
    truncation: true

Response:
  [
    [0.0234, -0.1567, ...]  # 1024 floats
  ]
```

**Version Registry Interface:**
```python
# src/services/embedding/version_registry.py
class EmbeddingVersionRegistry:
    async def get_active_version(self) -> ModelVersion:
        """Get the currently active embedding model version."""

    async def activate_version(self, version_id: str) -> None:
        """Activate a new version, deprecating the current active."""

    async def start_backfill(self, from_version: str, to_version: str, subject_id: UUID) -> UUID:
        """Start a backfill job. Returns job_id."""

    async def get_backfill_status(self, job_id: UUID) -> dict:
        """Get backfill progress."""
```

**Utterance Write with Stamp:**
```python
# Enforced at repository level
async def bulk_insert(self, subject_id: UUID, utterances: list[UtteranceCreate]) -> int:
    """Every utterance MUST have embed_model_ver set. Raises ValueError if missing."""
    for utt in utterances:
        if not utt.embed_model_ver:
            raise ValueError("embed_model_ver is required on every utterance")
    ...
```

**Retrieval Query with Version Filter:**
```sql
SELECT u.*, u.embedding <=> $1 AS distance
FROM utterances u
JOIN embedding_model_versions v ON u.embed_model_ver = v.version_id
WHERE u.subject_id = $2
  AND u.embedding IS NOT NULL
  AND v.status = 'active'
ORDER BY u.embedding <=> $1
LIMIT $3;
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Default |
|----------|------|-------------|---------|
| `TEI_ENDPOINT` | string | TEI service URL | `http://tei:8080` |
| `TEI_PORT` | int | TEI serving port | `8080` |
| `EMBEDDING_DIM` | int | Embedding dimension (frozen) | `1024` |
| `EMBEDDING_BATCH_SIZE` | int | Batch size for embedding | `32` |
| `EMBEDDING_FALLBACK_ENABLED` | bool | Use sentence-transformers if TEI down | `true` |
| `HF_HOME` | string | HuggingFace cache path | `/models/huggingface` |

**Third-Party Integration Contracts:**
- TEI: HuggingFace text-embeddings-inference HTTP API
- sentence-transformers: fallback embedding client
- pgvector: vector storage via S09 schema

**Version Pins:**
- TEI image pinned in Docker Compose
- Qwen3-Embedding-0.6B revision pinned in `config/models.yaml`

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T25.1 | I | `pytest tests/test_embedding_service.py::test_tei_returns_1024d -v` | TEI returns vectors of exactly 1024 dimensions |
| T25.2 | I | `pytest tests/test_embedding_service.py::test_write_requires_version -v` | Write without `embed_model_ver` rejected |
| T25.3 | I | `pytest tests/test_embedding_service.py::test_active_version_filter -v` | Retrieval with two versions present returns only active-version vectors |
| T25.4 | I | `pytest tests/test_embedding_service.py::test_backfill_atomic -v` | Backfill flow re-embeds one subject and switches active version atomically |
| T25.5 | P | `pytest tests/test_embedding_service.py::test_throughput -v` | 1,000 utterances embedded in < 60s |
| T25.6 | U | `pytest tests/test_embedding_service.py::test_instruction_prefix -v` | Instruction prefix applied correctly for clustering vs retrieval task modes |

**Test Case Details (Given/When/Then):**

**T25.1 — TEI returns 1024-dimensional vectors**
- **Given:** TEI service is running with Qwen3-Embedding-0.6B loaded
- **When:** 10 texts are sent to the embed endpoint
- **Then:** each returned vector has exactly 1024 elements, all floats

**T25.2 — Write without embed_model_ver rejected**
- **Given:** an utterance create payload without `embed_model_ver`
- **When:** attempting bulk insert via the repository
- **Then:** `ValueError` is raised; no rows inserted

**T25.3 — Active version filter in retrieval**
- **Given:** utterances embedded with two different model versions (v1=active, v2=deprecated)
- **When:** a vector query is executed
- **Then:** only utterances with `embed_model_ver=v1` are returned

**T25.4 — Backfill atomic version switch**
- **Given:** a subject with 10 sessions embedded under v1
- **When:** backfill to v2 is initiated
- **Then:** all 10 sessions are re-embedded; active version switches atomically; no partial state visible

**T25.5 — Throughput benchmark**
- **Given:** TEI service running, 1,000 utterance texts prepared
- **When:** batch embedding is executed
- **Then:** all 1,000 utterances embedded in under 60 seconds

**T25.6 — Instruction prefix applied correctly**
- **Given:** embedding client configured with retrieval and clustering prefixes
- **When:** embedding the same text with `task_mode=RETRIEVAL` and `task_mode=CLUSTERING`
- **Then:** the TEI request includes the correct instruction prefix; resulting vectors differ

**Verification Commands:**
```bash
docker compose up -d tei && \
sleep 60 && \
curl -f http://localhost:8080/health && \
uv run pytest tests/test_embedding_service.py -v -k "S25 or embedding_service" && \
uv run mypy --strict src/services/embedding/ && \
uv run ruff check src/services/embedding/
```

**Exit Criteria:**
- [ ] T25.1 passes — TEI returns 1024-dim vectors
- [ ] T25.2 passes — writes require `embed_model_ver`
- [ ] T25.3 passes — retrieval filters to active version only
- [ ] T25.4 passes — backfill is atomic and resumable
- [ ] T25.5 passes — 1,000 utterances in < 60s
- [ ] T25.6 passes — instruction prefix applied per task mode
- [ ] Embeddings are versioned such that a model change is a resumable migration, not an outage

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- TEI container startup can be slow on first run (model download) — pre-download weights in CI or use volume mount
- If `embed_model_ver` is not enforced at the application layer, DB NOT NULL catches it but with a less informative error
- Instruction prefix must be prepended to the text before sending to TEI, not as a separate parameter — TEI does not have a native instruction field
- Fallback to sentence-transformers adds ~2x latency; log clearly so operators know which backend served

**Fallback Instructions:**
- If TEI is down: sentence-transformers fallback handles embedding; alert operator
- If version registry is stale: read from `config/models.yaml` as source of truth
- If backfill fails mid-way: check `embedding_backfill_jobs` table for last completed session; resume from there

**Rollback Procedure:**
- Stop TEI container: `docker compose stop tei`
- Revert `config/models.yaml` to previous active version
- No schema migration rollback needed — version tables are additive
- Feature flag: `EMBEDDING_FALLBACK_ENABLED=false` forces TEI-only mode

---

### 9. Observability (if applicable)

**Metrics Added:**
- `embedding_request_total`: counter of embedding requests (labels: task_mode, backend=tei/fallback, status=success/error)
- `embedding_latency_seconds`: histogram of embedding request latency
- `embedding_dimension_check_total`: counter of dimension validation (labels: pass/fail)
- `embedding_model_version_active`: gauge indicating active version (labels: version_id)
- `embedding_backfill_progress`: gauge of backfill completion percentage

**Tracing/Logging:**
- Span: `embedding.embed` with attributes (text_count, task_mode, backend, latency_ms)
- Span: `embedding.version.activate` with attributes (from_version, to_version)
- Log: INFO on version activation and backfill completion
- Log: WARN on fallback activation
- Log: ERROR on TEI connection failure

**Alerts:**
- TEI health check failures > 3 in 5 minutes: service down
- Fallback activated > 10 times in 1 hour: TEI instability
- Backfill job stuck > 1 hour: investigate

---

### 10. Exit Checklist

- [ ] All tests pass (T25.1, T25.2, T25.3, T25.4, T25.5, T25.6)
- [ ] TEI serving Qwen3-Embedding-0.6B at 1024 dimensions
- [ ] Version registry operational in both `config/models.yaml` and DB
- [ ] Every utterance write stamps `embed_model_ver`
- [ ] Retrieval filters to active version only
- [ ] Backfill flow skeleton exists and is resumable
- [ ] Instruction prefix applied per task mode
- [ ] Embedding is a resumable migration, not an outage
