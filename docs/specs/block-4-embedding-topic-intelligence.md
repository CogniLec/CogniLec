# Block 4 — Embedding & Topic Intelligence: Stage Specifications (S25–S32)

**Source:** `LIS-implementation-plan-v1.md` lines 427–536
**Version:** 1.0
**Date:** 2026-09-12
**Status:** Living document — grounded in codebase state at time of writing

---

## Table of Contents

- [S25 — Embedding Service & Version Governance](#s25--embedding-service--version-governance)
- [S26 — Context-Window Embedding](#s26--context-window-embedding)
- [S27 — Prefect Setup & Embedding Task (T1)](#s27--prefect-setup--embedding-task-t1)
- [S28 — Boundary Detection (Segmentation)](#s28--boundary-detection-segmentation)
- [S29 ⛔ — Segmentation Evaluation (HARD GATE)](#s29--segmentation-evaluation-hard-gate)
- [S30 — Topic Clustering](#s30--topic-clustering)
- [S31 — Topic Labelling & Keyword Extraction](#s31--topic-labelling--keyword-extraction)
- [S32 — Cross-Session Topic Identity](#s32--cross-session-topic-identity)

---

## S25 — Embedding Service & Version Governance

### 1. Stage Identity

| Field | Value |
|---|---|
| **ID** | S25 |
| **Name** | Embedding Service & Version Governance |
| **Block** | B4 — Embedding & Topic Intelligence |
| **Owner** | ML/Infrastructure |
| **Estimate** | 3–4 days |

### 2. Context

Single ASR utterances are too sparse and noisy to embed meaningfully. Before any clustering or segmentation can happen, a robust embedding pipeline must exist — serving Qwen3-Embedding-0.6B at frozen 1024 dimensions (the only model fitting the 4GB VRAM constraint per ADR-015). Every embedding write must be stamped with a model version so that model upgrades are resumable migrations, not outages. The version registry lives in `config/models.yaml`. This stage establishes the embedding foundation that S26 (windowing), S27 (orchestration), S28 (segmentation), and S30 (clustering) all build upon.

**Preceding stages:** S06 (bake-off gates, model selection locked), S09 (utterance schema with `embedding` Vector(1024) and `embed_model_ver` columns).

### 3. Dependencies

| Dependency | Type | Notes |
|---|---|---|
| S06 | Upstream | Model locked: Qwen3-Embedding-0.6B, 1024 dim |
| S09 | Upstream | `utterances` table exists with `embedding` and `embed_model_ver` columns |
| ADR-015 | Constraint | 4GB VRAM — only Qwen3-0.6B fits |
| ADR-018 | Decision | Local-first, no hosted APIs for embedding |
| TEI service | External | Hugging Face Text Embeddings Inference (or sentence-transformers fallback) |
| `config/models.yaml` | Config | Version registry source of truth |

### 4. Requirements Traced

| ID | Source | Verbatim |
|---|---|---|
| FR-5.7 | SRS v1.0 | Every write stamps `embed_model_ver` |
| R-11 | SRS v1.0 §19 | Model version governance |
| ADR-015 | Architecture | 4GB VRAM constraint — Qwen3-0.6B only |

### 5. Interface Contracts

#### 5.1 SQL DDL (already exists from S09 migration `c58ea6212bc5`)

```sql
-- Already present in utterances table:
-- embedding Vector(1024), nullable
-- embed_model_ver String(50), NOT NULL
```

No new DDL. The schema is already in place.

#### 5.2 Config Schema (`config/models.yaml` — extend)

```yaml
# Existing (lines 12–17):
embedding_model: "Qwen/Qwen3-Embedding-0.6B"
embedding_dim: 1024
embedding_revision: "main"
embedding_device: "cuda"
embedding_batch_size: 32

# Add version governance fields:
embedding_versions:
  active: "qwen3-0.6b-v1"          # Current active version key
  registry:
    qwen3-0.6b-v1:
      model: "Qwen/Qwen3-Embedding-0.6B"
      dim: 1024
      revision: "main"
      instruction_prefix_retrieval: "Retrieve semantically similar content: "
      instruction_prefix_clustering: "Cluster semantically similar content: "
      registered_at: "2026-09-12"
      status: "active"
```

#### 5.3 Python Interface

```python
# src/ml/embedding/__init__.py
# New package — currently empty directory

# src/ml/embedding/client.py
class EmbeddingClient:
    """Async embedding client wrapping TEI or sentence-transformers."""

    async def embed(
        self,
        texts: list[str],
        task_mode: Literal["retrieval", "clustering"] = "retrieval",
    ) -> list[list[float]]:
        """Embed texts with appropriate instruction prefix."""
        ...

    async def health_check(self) -> bool:
        """Verify TEI service is reachable and returns correct dim."""
        ...
```

#### 5.4 Pydantic Schemas

```python
# src/ml/embedding/schemas.py
class EmbeddingRequest(BaseModel):
    texts: list[str]
    task_mode: Literal["retrieval", "clustering"] = "retrieval"
    model_version: str | None = None  # None = use active version


class EmbeddingResponse(BaseModel):
    embeddings: list[list[float]]
    model_version: str
    dim: int
    count: int


class ModelVersionInfo(BaseModel):
    key: str
    model: str
    dim: int
    status: Literal["active", "deprecated", "backfilling"]
    instruction_prefix_retrieval: str
    instruction_prefix_clustering: str
```

### 6. Implementation Notes

#### 6.1 TEI Service (Docker)

Add to `docker-compose.yml` under `services:`:

```yaml
tei:
  image: ghcr.io/huggingface/text-embeddings-inference:cpu-1.5
  container_name: lis-tei
  hostname: tei
  volumes:
    - models:/models
  command: --model-id Qwen/Qwen3-Embedding-0.6B --max-batch-tokens 16384
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:80/health"]
    interval: 30s
    timeout: 10s
    retries: 5
  networks:
    - internal
  deploy:
    resources:
      limits:
        memory: 2G
```

**Note:** TEI CPU image used because GPU is reserved for ASR. If GPU headroom available, switch to `gpu` variant for faster inference. The `models` volume is shared with the HF model cache.

#### 6.2 Fallback: sentence-transformers

If TEI is not deployable (e.g., VRAM contention), fall back to `sentence-transformers` running in-process. The client abstracts this:

```python
TEI_BASE_URL = "http://tei:80"
FALLBACK_LOCAL = True  # Use sentence-transformers if TEI unreachable
```

#### 6.3 Instruction Prefix

Qwen3-Embedding-0.6B is instruction-tuned. The prefix changes embedding behavior:
- **Retrieval mode:** `"Retrieve semantically similar content: "` — optimizes for cosine similarity search
- **Clustering mode:** `"Cluster semantically similar content: "` — optimizes for group coherence

Every text passed to the embedder must be prepended with the appropriate prefix based on `task_mode`.

#### 6.4 Version Registry Logic

```python
def get_active_version() -> ModelVersionInfo:
    """Read from config/models.yaml → embedding_versions.active"""
    ...


def stamp_version(embedding_row: dict, version: str) -> dict:
    """Set embed_model_ver on a row dict before insert."""
    embedding_row["embed_model_ver"] = version
    return embedding_row
```

#### 6.5 Backfill Flow Skeleton

```python
# src/ml/embedding/backfill.py
async def backfill_version(
    subject_id: uuid.UUID,
    from_version: str,
    to_version: str,
    batch_size: int = 100,
) -> BackfillResult:
    """Resumable backfill: re-embed all utterances for a subject.

    Process:
    1. Query utterances WHERE embed_model_ver = from_version
    2. Batch-embed with to_version model
    3. UPDATE embedding + embed_model_ver atomically per batch
    4. Record progress for resume on failure
    """
    ...
```

#### 6.6 Failure Handling

| Failure | Behavior |
|---|---|
| TEI unreachable | Fall back to sentence-transformers local |
| Embedding dim mismatch | Raise `DimensionError`, reject write |
| Missing `embed_model_ver` | Reject at repo level (NOT NULL constraint) |
| Partial backfill crash | Resume from last completed batch (track in a `backfill_progress` table or Valkey key) |

### 7. Test Specification

| ID | Type | Given | When | Then |
|---|---|---|---|---|
| T25.1 | I | TEI service running, Qwen3-0.6B loaded | POST 10 texts to `/embed` | Response contains 10 vectors, each exactly 1024 dimensions |
| T25.2 | I | Utterance dict without `embed_model_ver` | Attempt `UtteranceRepository.bulk_insert` | Rejected with `NotNullError` on `embed_model_ver` column |
| T25.3 | I | Two model versions present in `utterances` (v1 active, v2 deprecated) | Call `vector_query` with active version filter | Only rows with `embed_model_ver = active` returned |
| T25.4 | I | 5 utterances at `embed_model_ver = "old-v1"` | Run `backfill_version(subject, "old-v1", "new-v2")` | All 5 rows updated to `"new-v2"` atomically; query for `"old-v1"` returns empty |
| T25.5 | P | 1,000 utterance texts loaded | Embed via client | Completes in < 60 seconds |
| T25.6 | U | Texts: `["gradient descent", "neural network"]` | Embed with `task_mode="clustering"` | Instruction prefix `"Cluster semantically similar content: "` prepended to each before embedding; prefix verified via mock/assertion |

**Fixtures:**
- `fixture_te running` — Docker testcontainer with TEI (or mock)
- `fixture_utterances_batch` — 1,000 synthetic utterance texts
- `fixture_two_version_db` — Database with utterances at two different `embed_model_ver` values

### 8. Observability

| Type | Name | Details |
|---|---|---|
| Metric | `embedding_batch_size` | Histogram of batch sizes sent to TEI |
| Metric | `embedding_latency_seconds` | Histogram of embedding request latency |
| Metric | `embedding_dimension_errors` | Counter of dimension mismatches |
| Span | `embedding.embed` | OpenTelemetry span wrapping each embed call |
| Log | `embedding.version_active` | INFO on startup: active model version |
| Log | `embedding.fallback_local` | WARNING when falling back from TEI to local |

### 9. Rollback

- **Code:** Revert `src/ml/embedding/` package. No other code depends on it yet (S26–S32 not started).
- **Config:** Remove `embedding_versions` key from `config/models.yaml`.
- **Docker:** Remove `tei` service from `docker-compose.yml`.
- **Data:** No migration — existing `embedding` and `embed_model_ver` columns are untouched.
- **Feature flag:** `EMBEDDING_SERVICE_ENABLED` env var (default `true`). Set `false` to disable.

### 10. Exit Checklist

- [ ] TEI service (or sentence-transformers fallback) returns vectors of exactly 1024 dimensions
- [ ] Every embedding write includes `embed_model_ver`; writes without it are rejected
- [ ] Retrieval with two versions present returns only active-version vectors
- [ ] Backfill flow re-embeds one subject and switches its active version atomically
- [ ] 1,000 utterances embedded in < 60s
- [ ] Instruction prefix applied correctly for clustering vs retrieval task modes
- [ ] All tests T25.1–T25.6 pass

**Closing condition:** Embeddings are versioned such that a model change is a resumable migration, not an outage.

---

## S26 — Context-Window Embedding

### 1. Stage Identity

| Field | Value |
|---|---|
| **ID** | S26 |
| **Name** | Context-Window Embedding |
| **Block** | B4 |
| **Owner** | ML |
| **Estimate** | 2–3 days |

### 2. Context

Single ASR utterances are too sparse and noisy to embed meaningfully. S25 provides the embedding service; S26 solves the input quality problem by embedding **overlapping blocks** of W preceding utterances plus the current one, rather than isolated utterances. This windowed approach produces embeddings that capture local discourse context, measurably improving clustering purity. The window size W is configurable and defaults to the value determined by S06 experimentation.

**Preceding stages:** S25 (embedding service operational).

### 3. Dependencies

| Dependency | Type | Notes |
|---|---|---|
| S25 | Upstream | Embedding client with version governance |
| S06 experimentation | Config | W default value from bake-off |
| `utterances` table | Schema | `seq` column for ordering, `text` for concatenation |

### 4. Requirements Traced

| ID | Source | Verbatim |
|---|---|---|
| ML-4 | SRS v1.0 | Context-window embedding strategy |

### 5. Interface Contracts

#### 5.1 Config

```yaml
# config/models.yaml — add:
embedding:
  window_size: 5          # W: number of preceding utterances to include
  window_stride: 1        # Sliding window stride
  min_window: 1           # Minimum window (at transcript start)
```

#### 5.2 Python Interface

```python
# src/ml/embedding/windowing.py
@dataclass
class WindowedUtterance:
    """An utterance with its context window assembled."""

    utterance_id: uuid.UUID
    seq: int
    window_text: str  # Concatenated text of W predecessors + current
    window_size_actual: int  # Actual number of utterances in window (may be < W at start)
    individual_text: str  # Original single-utterance text


def build_windows(
    utterances: list[Utterance],
    W: int = 5,
    stride: int = 1,
) -> list[WindowedUtterance]:
    """Build overlapping context windows over ordered utterances.

    At transcript start (fewer than W predecessors), window shrinks.
    At transcript end, window includes all available successors.
    W=0 degenerates to isolated embedding (each utterance alone).
    """
    ...
```

#### 5.3 Embedding Pipeline Integration

```python
# src/ml/embedding/pipeline.py
async def embed_session_windowed(
    subject_id: uuid.UUID,
    session_id: uuid.UUID,
    client: EmbeddingClient,
    W: int = 5,
    task_mode: Literal["retrieval", "clustering"] = "clustering",
) -> list[WindowedEmbeddingResult]:
    """Embed all utterances in a session using context windows.

    Returns list of (utterance_id, embedding, window_size) tuples.
    """
    ...
```

### 6. Implementation Notes

#### 6.1 Window Construction Algorithm

```
for i in 0..len(utterances)-1:
    start = max(0, i - W)
    window = utterances[start:i+1]
    window_text = " ".join(u.text for u in window)
    yield WindowedUtterance(
        utterance_id=utterances[i].id,
        seq=utterances[i].seq,
        window_text=window_text,
        window_size_actual=len(window),
        individual_text=utterances[i].text,
    )
```

#### 6.2 Benchmark

S26 requires a comparative benchmark proving windowed embeddings outperform isolated. Use S05 labeled data:

```python
# scripts/s26_window_benchmark.py
# Compare purity of:
# 1. Isolated embedding (W=0)
# 2. Windowed embedding (W=5, W=10, W=15)
# Report: purity, V-measure, clustering time
```

#### 6.3 Failure Handling

| Failure | Behavior |
|---|---|
| W > number of utterances | Window shrinks to available utterances (no error) |
| W = 0 | Degenerates to isolated embedding |
| Empty utterance list | Return empty list |
| Concatenated window exceeds model max tokens | Truncate to model limit, log warning |

### 7. Test Specification

| ID | Type | Given | When | Then |
|---|---|---|---|---|
| T26.1 | U | 10 utterances, W=5, at utterance index 0 | Build windows | Window contains only utterance 0 (`window_size_actual=1`) |
| T26.1b | U | 10 utterances, W=5, at utterance index 9 | Build windows | Window contains utterances 5–9 (`window_size_actual=5`) |
| T26.2 | V | S05 labeled data (30 lectures), W=0 vs W=5 | Embed both ways, cluster, compute purity | Windowed purity > isolated purity by ≥ 0.05 |
| T26.3 | U | Config with W=0 | Build windows | Each window contains exactly 1 utterance (isolated) |
| T26.3b | U | Config with W=10 | Build windows at index 3 | `window_size_actual=4` (indices 0–3) |
| T26.4 | P | 1,000 utterances, W=5 | Embed with windowing | Total embedding time < 1.2× isolated embedding time (adds < 20%) |

**Fixtures:**
- `fixture_10_utterances` — Ordered list of 10 `Utterance` objects
- `fixture_s05_labeled` — S05 hand-labeled transcripts (30 lectures)
- `fixture_embedding_client_mock` — Mock `EmbeddingClient` returning random 1024-dim vectors

### 8. Observability

| Type | Name | Details |
|---|---|---|
| Metric | `embedding_window_size_actual` | Histogram of actual window sizes per utterance |
| Metric | `embedding_windowing_overhead_ratio` | Ratio of windowed vs isolated embedding time |
| Span | `embedding.build_windows` | Time to construct windows for a session |
| Span | `embedding.embed_session_windowed` | Full windowed embedding pipeline span |

### 9. Rollback

- **Code:** Remove `src/ml/embedding/windowing.py` and `src/ml/embedding/pipeline.py`.
- **Config:** Set `window_size: 0` in `config/models.yaml` to disable windowing.
- **Data:** No schema changes — embeddings are overwritten in place.
- **Feature flag:** `EMBEDDING_WINDOW_SIZE` env var. Set `0` for isolated mode.

### 10. Exit Checklist

- [ ] Window construction correct at transcript start (fewer than W predecessors) and end
- [ ] Windowed embeddings produce higher clustering purity than isolated-utterance embeddings on S05 labels
- [ ] W is configurable; W=0 degenerates to isolated embedding
- [ ] Windowing adds < 20% to embedding time
- [ ] All tests T26.1–T26.4 pass

**Closing condition:** Windowed embedding measurably outperforms naive embedding; W chosen on evidence.

---

## S27 — Prefect Setup & Embedding Task (T1)

### 1. Stage Identity

| Field | Value |
|---|---|
| **ID** | S27 |
| **Name** | Prefect Setup & Embedding Task (T1) |
| **Block** | B4 |
| **Owner** | Infrastructure/ML |
| **Estimate** | 3–4 days |

### 2. Context

S25 provides the embedding service; S26 provides windowing. S27 wires them into a durable, observable, event-driven orchestration pipeline using Prefect (per ADR-001). The `process_session` flow is triggered by the `session.transcribed` event and runs task T1 (`embed_utterances`). Task results are cached on `(session_id, embed_model_ver)` to prevent re-embedding. The flow includes the NFR-R3 assertion gate at entry (session must be `transcribed` status).

**Preceding stages:** S26 (windowing), S23 (session status transitions).

### 3. Dependencies

| Dependency | Type | Notes |
|---|---|---|
| S26 | Upstream | Windowed embedding pipeline |
| S23 | Upstream | Session status transitions (`transcribed` state) |
| ADR-001 | Decision | Prefect orchestration |
| ADR-002 | Decision | Worker pool topology (`ml-pool`) |
| ADR-003 | Decision | Event-driven triggers (`session.transcribed`) |
| Prefect server | External | Prefect 3.x (in `pyproject.toml`) |

### 4. Requirements Traced

| ID | Source | Verbatim |
|---|---|---|
| FR-5.6 | SRS v1.0 | Pipeline orchestration for embedding |
| NFR-R4 | SRS v1.0 | Resumable pipeline execution |
| NFR-R6 | SRS v1.0 | Idempotent task execution |
| ADR-001 | Architecture | Prefect for orchestration |

### 5. Interface Contracts

#### 5.1 Event Schema

```python
# Event: session.transcribed
class SessionTranscribedEvent(BaseModel):
    session_id: uuid.UUID
    subject_id: uuid.UUID
    utterance_count: int
    embed_model_ver: str
    timestamp: datetime
```

#### 5.2 Flow Definition

```python
# src/ml/embedding/flows.py
from prefect import flow, task, get_run_logger


@task(
    name="T1_embed_utterances",
    cache_key_fn=lambda ctx, *args: (
        f"T1-{ctx.parameters['session_id']}-{ctx.parameters['embed_model_ver']}"
    ),
    cache_expiration=timedelta(hours=24),
    retries=2,
    retry_delay_seconds=30,
)
async def embed_utterances(
    session_id: uuid.UUID,
    subject_id: uuid.UUID,
    embed_model_ver: str,
) -> EmbeddingResult:
    """T1: Embed all utterances in a session using context windows.

    Cached on (session_id, embed_model_ver).
    Idempotent: re-running with same params returns cached result.
    """
    ...


@flow(
    name="process_session",
    flow_run_name="process-{session_id}",
    retries=0,  # Flow-level: no retry, task-level has retry
)
async def process_session(
    session_id: uuid.UUID,
    subject_id: uuid.UUID,
    embed_model_ver: str,
) -> ProcessSessionResult:
    """Main session processing flow.

    Entry gate: session status must be 'transcribed' (NFR-R3).
    """
    logger = get_run_logger()

    # NFR-R3 assertion gate
    session = await get_session(subject_id, session_id)
    if session.status != SessionStatus.TRANSCRIBED:
        raise FlowAbortError(
            f"Session {session_id} status is '{session.status}', expected 'transcribed'"
        )

    # Mark processing
    await update_session_status(session_id, SessionStatus.PROCESSING)

    try:
        # T1: Embed utterances
        embedding_result = await embed_utterances(
            session_id=session_id,
            subject_id=subject_id,
            embed_model_ver=embed_model_ver,
        )

        # Future: T2 (segmentation), T3 (clustering) will be added here

        await update_session_status(session_id, SessionStatus.COMPLETE)
        return ProcessSessionResult(success=True, embedding_result=embedding_result)

    except Exception as e:
        logger.error("Flow failed: %s", e)
        await update_session_status(session_id, SessionStatus.FAILED)
        emit_event(
            "session.failed",
            {
                "session_id": session_id,
                "subject_id": subject_id,
                "error": str(e),
            },
        )
        raise
```

#### 5.3 Prefect Deployment

```python
# Deployment config (prefect.yaml or programmatic)
deployment:
  name: process-session
  flow: src.ml.embedding.flows:process_session
  work_pool: ml-pool
  work_queue: embedding
  parameters: {}
  triggers:
    - type: event
      expect: ["session.transcribed"]
```

### 6. Implementation Notes

#### 6.1 Worker Pool Setup

Per ADR-002, the `ml-pool` handles GPU workloads:

```
prefect work-pool create ml-pool --type process
prefect work-pool create llm-pool --type process
prefect work-pool create cpu-pool --type process
```

Workers started with:
```
prefect worker start --pool ml-pool --type process
```

#### 6.2 Caching Strategy

- **Cache key:** `f"T1-{session_id}-{embed_model_ver}"`
- **Cache expiration:** 24 hours
- **Invalidation:** Changing `embed_model_ver` automatically invalidates (different key)
- **Re-run:** Same `(session_id, embed_model_ver)` reuses cached T1 results

#### 6.3 Idempotency (NFR-R6)

- T1 uses `INSERT ... ON CONFLICT (subject_id, session_id, seq) DO UPDATE` for utterance writes
- Embedding vector update is idempotent (same input → same output)
- If worker killed mid-task, Prefect retries; no duplicate rows due to upsert semantics

#### 6.4 Prefect Server (Docker)

Add to `docker-compose.yml`:

```yaml
prefect-server:
  image: prefecthq/prefect:3-latest
  container_name: lis-prefect
  hostname: prefect
  command: prefect server start --host 0.0.0.0 --port 4200
  ports:
    - "4200:4200"
  environment:
    PREFECT_API_DATABASE_CONNECTION_URL: postgresql+asyncpg://lis:lis_dev@pg-main:5432/lis_main
  networks:
    - internal
  depends_on:
    pg-main:
      condition: service_healthy
  deploy:
    resources:
      limits:
        memory: 1G
```

#### 6.5 Failure Handling

| Failure | Behavior |
|---|---|
| Session not `transcribed` | Flow aborts with `FlowAbortError`, no processing |
| T1 fails | Retried 2× with 30s delay; on final failure, session marked `failed` |
| Worker killed mid-task | Prefect reschedules; idempotent writes prevent duplicates |
| TEI unreachable | T1 falls back to sentence-transformers (S25) |
| Flow failure | Session status → `failed`, `session.failed` event emitted |

### 7. Test Specification

| ID | Type | Given | When | Then |
|---|---|---|---|---|
| T27.1 | I | Session in `transcribed` status | Emit `session.transcribed` event | Flow triggers automatically within 30s |
| T27.2 | I | Session in `created` status | Attempt to start `process_session` flow | Flow refuses to start (NFR-R3 gate); raises `FlowAbortError` |
| T27.3 | I | Session already embedded with `embed_model_ver="v1"` | Re-run flow with same `embed_model_ver="v1"` | T1 returns cached result; no re-embedding; DB unchanged |
| T27.4 | I | Session embedded with `embed_model_ver="v1"` | Run flow with `embed_model_ver="v2"` | Cache miss; T1 re-embeds with v2; DB updated |
| T27.5 | I | T1 running, worker killed (simulate SIGKILL) | Worker restarts | Prefect reschedules T1; utterance count unchanged (no duplicates) |
| T27.6 | I | T1 raises unhandled exception | Flow completes | Session status → `failed`; `session.failed` event emitted with error message |

**Fixtures:**
- `fixture_session_transcribed` — Session with status `transcribed`, 50 utterances
- `fixture_session_created` — Session with status `created`
- `fixture_prefect_server` — Prefect testcontainer or mock
- `fixture_utterances_with_embeddings` — Session with utterances already embedded

### 8. Observability

| Type | Name | Details |
|---|---|---|
| Metric | `flow_process_session_runs` | Counter of flow runs by status (completed/failed/aborted) |
| Metric | `task_T1_duration_seconds` | Histogram of T1 execution time |
| Metric | `task_T1_cache_hit` | Counter of cache hits vs misses |
| Span | `flow.process_session` | Full flow trace |
| Span | `task.T1_embed_utterances` | T1 task trace |
| Log | `flow.nfr_r3_gate_failed` | WARNING when session not in `transcribed` status |

### 9. Rollback

- **Code:** Remove `src/ml/embedding/flows.py`. No other code depends on it.
- **Docker:** Remove `prefect-server` service from `docker-compose.yml`.
- **Config:** Remove Prefect deployment via `prefect deployment delete process-session`.
- **Data:** No schema changes.
- **Feature flag:** `PREFECT_ENABLED` env var. Set `false` to disable event-driven triggering.

### 10. Exit Checklist

- [ ] Flow triggers automatically on `session.transcribed`
- [ ] Flow refuses to start if session status is not `transcribed` (NFR-R3)
- [ ] Re-running the flow reuses cached T1 results (no re-embedding)
- [ ] Changing `embed_model_ver` invalidates the cache and re-embeds
- [ ] Worker killed mid-task → task retried, no duplicate rows (idempotency, NFR-R6)
- [ ] Flow failure marks session `failed` and emits the event
- [ ] All tests T27.1–T27.6 pass

**Closing condition:** The orchestrated pipeline exists, is event-driven, cached, and idempotent.

---

## S28 — Boundary Detection (Segmentation)

### 1. Stage Identity

| Field | Value |
|---|---|
| **ID** | S28 |
| **Name** | Boundary Detection (Segmentation) |
| **Block** | B4 |
| **Owner** | ML |
| **Estimate** | 3–4 days |

### 2. Context

After embedding (S25/S26) and orchestration (S27), the next step is dividing a session's utterance stream into **ordered, contiguous, non-overlapping segments** — each representing a coherent topic unit. This is a custom TextTiling-style algorithm over windowed embeddings: adjacent-block cosine similarity with an adaptively determined threshold. No existing library handles this well on ASR output (per ADR-006). Segments are written to the `segments` table with `boundary_score`. This is the structural foundation that S29 evaluates and S30 clusters on top of.

**Preceding stages:** S26 (windowed embeddings available), S09 (segments table exists).

### 3. Dependencies

| Dependency | Type | Notes |
|---|---|---|
| S26 | Upstream | Windowed embeddings |
| S09 | Upstream | `segments` table with `start_utt`, `end_utt`, `boundary_score` |
| ADR-006 | Decision | Custom TextTiling segmentation approach |
| S13 | Synthetic data | Synthetic transcripts with known boundaries for testing |

### 4. Requirements Traced

| ID | Source | Verbatim |
|---|---|---|
| FR-2.8 | SRS v1.0 | Segment detection from transcript |
| FR-5.9 | SRS v1.0 | Segment metadata persistence |
| ML-7 | SRS v1.0 | Segmentation algorithm |
| ADR-006 | Architecture | Custom TextTiling over windowed embeddings |
| §12.2 | Architecture | Segment-first-then-cluster ordering |

### 5. Interface Contracts

#### 5.1 SQL DDL (already exists from S09)

```sql
-- Already present:
-- segments table with: subject_id, id, session_id, start_utt, end_utt,
--   topic_id, boundary_score, confidence, created_at
```

No new DDL needed.

#### 5.2 Python Interface

```python
# src/ml/clustering/segmentation.py
@dataclass
class SegmentResult:
    """A detected segment within a session."""

    start_utt_id: uuid.UUID
    end_utt_id: uuid.UUID
    start_idx: int  # 0-based index in utterance list
    end_idx: int  # 0-based index (inclusive)
    boundary_score: float  # Cosine similarity at boundary (lower = sharper boundary)
    confidence: float  # Derived from score distribution


@dataclass
class SegmentationResult:
    """Complete segmentation of a session."""

    session_id: uuid.UUID
    segments: list[SegmentResult]
    num_segments: int
    similarity_scores: list[float]  # Adjacent-window cosine similarities


def segment_session(
    utterances: list[Utterance],
    embeddings: list[list[float]],
    threshold_percentile: float = 25.0,
) -> SegmentationResult:
    """Segment a session using adaptive TextTiling over windowed embeddings.

    Algorithm:
    1. Compute cosine similarity between adjacent windowed embeddings
    2. Determine adaptive threshold as percentile of similarity distribution
    3. Mark boundaries where similarity < threshold
    4. Produce ordered, contiguous, non-overlapping segments

    Every utterance belongs to exactly one segment.
    """
    ...
```

#### 5.3 Segment Persistence

```python
# src/ml/clustering/segment_repo.py (extend existing segment_repo.py)
async def persist_segments(
    subject_id: uuid.UUID,
    session_id: uuid.UUID,
    result: SegmentationResult,
) -> int:
    """Bulk persist segments to database."""
    ...
```

### 6. Implementation Notes

#### 6.1 Algorithm Detail

```
Input: ordered embeddings E[0..n-1], threshold percentile P

1. similarities[i] = cosine(E[i], E[i+1])  for i in 0..n-2
2. threshold = percentile(similarities, P)
3. boundaries = [i for i in range(n-1) if similarities[i] < threshold]
4. segments = []
   start = 0
   for b in boundaries:
       segments.append(Segment(start_utt=E[start].id, end_utt=E[b].id, ...))
       start = b + 1
   segments.append(Segment(start_utt=E[start].id, end_utt=E[n-1].id, ...))

Output: ordered, contiguous, non-overlapping segments
```

#### 6.2 Adaptive Threshold

The threshold is not fixed — it adapts to each session's similarity distribution. `threshold_percentile=25` means the bottom 25% of similarities are considered boundaries. This handles:
- Fast-topic-shift lectures (wider spread → more segments)
- Slow-monologue lectures (narrow spread → fewer segments)

#### 6.3 Boundary Score

`boundary_score` is the cosine similarity at the boundary point. Lower scores indicate sharper topic shifts. This feeds into downstream confidence calculations and can be used for filtering low-confidence segments.

#### 6.4 Failure Handling

| Failure | Behavior |
|---|---|
| 0 or 1 utterances | Return single segment covering all |
| All embeddings identical | Similarities all 1.0, no boundaries found, single segment |
| Embedding dim mismatch | Raise `DimensionError` |
| No boundaries found (threshold too high) | Return single segment (session = one topic) |

### 7. Test Specification

| ID | Type | Given | When | Then |
|---|---|---|---|---|
| T28.1 | U | Random transcript with 50 utterances, Hypothesis strategy | Segment | Segments are contiguous (end_i+1 == next start_i), ordered, non-overlapping |
| T28.2 | U | Any transcript of N utterances | Segment | Sum of (end_idx - start_idx + 1) across all segments == N; every utterance index appears exactly once |
| T28.3 | V | Synthetic transcript with 3 known boundaries (S13 generator) | Segment | Boundaries recovered within ±2 utterances of ground truth |
| T28.4 | V | Synthetic transcript, single topic (30 utterances, same template) | Segment | Produces exactly 1 segment (no spurious splits) |
| T28.5 | P | 1,000 utterances with pre-computed embeddings | Segment | Completes in < 10 seconds |

**Fixtures:**
- `fixture_50_random_utterances` — 50 ordered utterances with random embeddings
- `fixture_synthetic_3topic` — S13-generated transcript with 3 known boundaries
- `fixture_single_topic_30` — 30 utterances from same topic template

### 8. Observability

| Type | Name | Details |
|---|---|---|
| Metric | `segmentation_segments_count` | Histogram of segments per session |
| Metric | `segmentation_boundary_scores` | Histogram of boundary scores |
| Metric | `segmentation_duration_seconds` | Histogram of segmentation time |
| Span | `segmentation.segment_session` | Full segmentation trace |

### 9. Rollback

- **Code:** Remove `src/ml/clustering/segmentation.py`. No downstream code depends on it yet (S29 gates all further work).
- **Data:** Truncate `segments` table. No DDL changes.
- **Feature flag:** `SEGMENTATION_ENABLED` env var. Set `false` to skip segmentation in flow.

### 10. Exit Checklist

- [ ] Segments are contiguous, ordered and non-overlapping (Hypothesis property test)
- [ ] Every utterance belongs to exactly one segment
- [ ] On synthetic transcripts with known boundaries, boundaries recovered within ±2 utterances
- [ ] A single-topic lecture yields one segment, not spurious splits
- [ ] Segmentation of 1,000 utterances completes in < 10s
- [ ] All tests T28.1–T28.5 pass

**Closing condition:** Segmentation produces structurally valid, ordered segments on both synthetic and real transcripts.

---

## S29 ⛔ — Segmentation Evaluation (HARD GATE)

### 1. Stage Identity

| Field | Value |
|---|---|
| **ID** | S29 |
| **Name** | Segmentation Evaluation (HARD GATE) |
| **Block** | B4 |
| **Owner** | ML/Evaluation |
| **Estimate** | 2–3 days |

### 2. Context

S28 produces segments. S29 is the **hard gate** (⛔) that validates segmentation quality before any clustering is built on top of it. Clustering inherits segmentation error directly — if segments are wrong, topics will be wrong. The evaluation uses **P_k and WindowDiff** against the 30 hand-marked lectures from S05. If the gate fails, the segmentation approach must be revised before proceeding.

**Preceding stages:** S28 (segmentation algorithm), S05 (ground truth labels).

### 3. Dependencies

| Dependency | Type | Notes |
|---|---|---|
| S28 | Upstream | Segmentation algorithm |
| S05 | Upstream | 30 hand-marked lectures (ground truth) |
| `src/eval/harness.py` | Existing | `_eval_segmentation` function using segeval |
| segeval library | Dependency | P_k and WindowDiff computation |

### 4. Requirements Traced

| ID | Source | Verbatim |
|---|---|---|
| Phase 2 gate | Implementation plan | Segmentation quality gate before clustering |
| §12.4 | Architecture | Evaluation methodology |

### 5. Interface Contracts

#### 5.1 Evaluation Script

```python
# scripts/s29_segmentation_eval.py
async def evaluate_segmentation(
    ground_truth_dir: str = "data/ground_truth/s05_handmarked/",
    model: str = "qwen3-0.6b",
    W: int = 5,
    threshold_percentile: float = 25.0,
) -> SegmentationEvalReport:
    """Evaluate segmentation against S05 hand-marked boundaries.

    Returns:
        P_k, WindowDiff, per-condition breakdown, baseline comparisons
    """
    ...
```

#### 5.2 Report Schema

```python
# src/eval/segmentation_report.py
class SegmentationEvalReport(BaseModel):
    pk_score: float
    window_diff: float
    gate_passed: bool  # pk < 0.30
    baseline_random_pk: float
    baseline_fixed_window_pk: float
    beats_baselines: bool  # pk < min(random_pk, fixed_window_pk) - margin
    per_condition: dict[str, ConditionMetrics]  # "discussion_heavy" vs "monologue"
    threshold_used: float
    num_lectures_evaluated: int


class ConditionMetrics(BaseModel):
    pk: float
    window_diff: float
    num_lectures: int
```

#### 5.3 Baselines

```python
# Baselines to compare against:
baselines = {
    "random": RandomSegmentation(seed=42),  # Random boundary placement
    "fixed_window": FixedWindowSegmentation(window=20),  # Every 20 utterances
}
```

### 6. Implementation Notes

#### 6.1 Gate Criteria

| Metric | Threshold | Rationale |
|---|---|---|
| **P_k** | < 0.30 | Standard segmentation quality threshold |
| **WindowDiff** | Recorded | Supplementary metric |
| **vs baselines** | Beats both by clear margin | Guards against trivially passing |

#### 6.2 Threshold Tuning

The evaluation iterates over `threshold_percentile` values (10, 15, 20, 25, 30, 35, 40) and selects the one that minimizes P_k on a validation split. The tuned threshold is then locked for production.

#### 6.3 Per-Condition Analysis

Results broken down by:
- **Discussion-heavy lectures** (more topic shifts, student interruptions)
- **Monologue lectures** (steady topic flow, fewer boundaries)

This identifies where the algorithm struggles.

#### 6.4 Failure Handling

| Failure | Behavior |
|---|---|
| Gate fails (P_k ≥ 0.30) | **STOP.** Do not proceed to S30. Revise segmentation approach. |
| Baselines beat segmentation | **STOP.** Segmentation is worse than random — fundamental issue |
| Insufficient S05 data | Report available lectures; flag as partial gate |

### 7. Test Specification

| ID | Type | Given | When | Then |
|---|---|---|---|---|
| T29.1 | V | 30 S05 hand-marked lectures, tuned threshold | Evaluate P_k on held-out set | **GATE: P_k < 0.30** |
| T29.2 | V | Same setup as T29.1 | Record WindowDiff | WindowDiff value recorded in report alongside P_k |
| T29.3 | V | Same setup, plus random and fixed-window baselines | Compare P_k | Segmentation P_k < min(random_pk, fixed_window_pk) − 0.05 margin |
| T29.4 | V | Lectures split by condition (discussion vs monologue) | Report per condition | Both conditions have P_k < 0.35 (individual condition may be slightly relaxed) |

**Fixtures:**
- `fixture_s05_handmarked_30` — 30 hand-marked lectures with boundary annotations
- `fixture_synthetic_baselines` — Pre-computed baseline results

### 8. Observability

| Type | Name | Details |
|---|---|---|
| Metric | `eval_segmentation_pk` | Gauge of P_k score |
| Metric | `eval_segmentation_window_diff` | Gauge of WindowDiff score |
| Metric | `eval_segmentation_gate_passed` | Gauge (0/1) of gate status |
| Artifact | `segmentation_eval_report.json` | Full evaluation report saved to MLflow |

### 9. Rollback

- **Code:** Remove `scripts/s29_segmentation_eval.py`. Evaluation is read-only.
- **Data:** No schema changes.
- **Gate enforcement:** If gate fails, S30 (clustering) does not start. This is enforced by the stage dependency chain, not by code.
- **Feature flag:** None — this is a gate, not a feature.

### 10. Exit Checklist

- [ ] **GATE: P_k < 0.30 on the held-out set** ← MANDATORY
- [ ] WindowDiff recorded alongside P_k
- [ ] Beats random and fixed-window baselines by a clear margin ← MANDATORY
- [ ] Performance reported per condition (discussion-heavy vs monologue)
- [ ] All tests T29.1–T29.4 pass

**Closing condition:** T29.1 and T29.3 pass. If not, segmentation approach is revised before clustering is built on top of it.

---

## S30 — Topic Clustering

### 1. Stage Identity

| Field | Value |
|---|---|
| **ID** | S30 |
| **Name** | Topic Clustering |
| **Block** | B4 |
| **Owner** | ML |
| **Estimate** | 4–5 days |

### 2. Context

With validated segments from S29, S30 clusters **segment embeddings** (not raw utterances) into topics using BERTopic (UMAP + HDBSCAN). The segment-first-then-cluster ordering per §12.2 ensures that clustering operates on meaningful discourse units. Each segment's member embeddings are mean-pooled to produce a single segment embedding. Topics are persisted with centroids and keywords. The HDBSCAN outlier score on each utterance feeds into A1 (relevance filtering) downstream.

**Preceding stages:** S29 (gate passed), S27 (Prefect orchestration with T1).

### 3. Dependencies

| Dependency | Type | Notes |
|---|---|---|
| S29 | Upstream (gate) | Validated segments |
| S27 | Upstream | Prefect orchestration |
| S26 | Upstream | Windowed embeddings on utterances |
| BERTopic | Library | `bertopic>=0.16` in `pyproject.toml` |
| UMAP | Library | `umap-learn>=0.5.6` in `pyproject.toml` |
| HDBSCAN | Library | `hdbscan>=0.8.33` in `pyproject.toml` |
| ADR-010 | Decision | Subject-scoped topic identity |

### 4. Requirements Traced

| ID | Source | Verbatim |
|---|---|---|
| FR-2.6 | SRS v1.0 | Topic clustering from segments |
| FR-5.3 | SRS v1.0 | Topic identity across sessions |
| FR-5.8 | SRS v1.0 | Multiple topics per session |
| ML-5 | SRS v1.0 | Clustering algorithm |
| §12.2 | Architecture | Segment-first-then-cluster ordering |

### 5. Interface Contracts

#### 5.1 SQL DDL — `topics` table (NEW)

```sql
CREATE TABLE topics (
    subject_id UUID NOT NULL,
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    session_id UUID,                          -- First session that created this topic
    centroid VECTOR(1024) NOT NULL,           -- Mean segment embedding
    label VARCHAR(200),                       -- Human-editable label (S31)
    keywords TEXT[],                          -- c-TF-IDF + KeyBERT keywords (S31)
    keyword_scores FLOAT[],                   -- Corresponding scores
    segment_count INT NOT NULL DEFAULT 0,     -- Number of segments assigned
    utterance_count INT NOT NULL DEFAULT 0,   -- Total utterances in this topic
    is_user_edited BOOLEAN NOT NULL DEFAULT FALSE,  -- Preserve user edits (S31)
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (subject_id, id)
);

-- Index for nearest-centroid queries (S32)
CREATE INDEX idx_topics_centroid ON topics
    USING hnsw (centroid vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- FK to sessions
ALTER TABLE topics ADD CONSTRAINT fk_topics_session
    FOREIGN KEY (session_id) REFERENCES sessions(id);
```

#### 5.2 Pydantic Schemas

```python
# src/ml/clustering/schemas.py
class TopicCreate(BaseModel):
    session_id: uuid.UUID
    centroid: list[float]
    label: str | None = None
    keywords: list[str] = []
    keyword_scores: list[float] = []
    segment_count: int = 0
    utterance_count: int = 0


class TopicResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    subject_id: uuid.UUID
    session_id: uuid.UUID | None
    centroid: list[float]
    label: str | None
    keywords: list[str]
    is_user_edited: bool
    segment_count: int
    utterance_count: int
    created_at: datetime


class ClusteringResult(BaseModel):
    session_id: uuid.UUID
    topics_created: int
    segments_assigned: int
    outliers: int  # Segments marked as noise by HDBSCAN
    topic_assignments: list[SegmentTopicAssignment]


class SegmentTopicAssignment(BaseModel):
    segment_id: uuid.UUID
    topic_id: uuid.UUID | None  # None for outliers
    outlier_score: float
    is_outlier: bool
```

#### 5.3 Task T3 Definition

```python
# src/ml/clustering/tasks.py
@task(
    name="T3_cluster_segments",
    cache_key_fn=lambda ctx, *args: f"T3-{ctx.parameters['session_id']}",
    cache_expiration=timedelta(hours=24),
    retries=1,
    retry_delay_seconds=60,
)
async def cluster_segments(
    session_id: uuid.UUID,
    subject_id: uuid.UUID,
) -> ClusteringResult:
    """T3: Cluster segment embeddings into topics.

    1. Load segments and their member utterance embeddings
    2. Mean-pool each segment's embeddings → segment embedding
    3. Run BERTopic on segment embeddings (UMAP + HDBSCAN)
    4. Persist topics with centroids
    5. Update segments with topic_id
    6. Store HDBSCAN outlier scores on utterances
    """
    ...
```

### 6. Implementation Notes

#### 6.1 BERTopic Configuration

From `scripts/s06_embedding_bakeoff.py` (validated hyperparameters):

```python
UMAP_CONFIG = {
    "n_neighbors": 15,
    "n_components": 5,
    "metric": "cosine",
    "random_state": 42,
}

HDBSCAN_CONFIG = {
    "min_cluster_size": 5,
    "min_samples": 3,
    "metric": "euclidean",
    "cluster_selection_method": "eom",
}
```

#### 6.2 Mean-Pooling

```python
import numpy as np


def mean_pool_segment(embeddings: list[list[float]]) -> list[float]:
    """Mean-pool utterance embeddings within a segment."""
    return np.mean(embeddings, axis=0).tolist()
```

#### 6.3 Scoping

Clustering is **strictly within one subject** (FR-2.10, FR-6.5). The `subject_id` partition key on all tables enforces this. Queries never cross subject boundaries.

#### 6.4 Outlier Score Persistence

HDBSCAN assigns `-1` topic label for noise. Additionally, it provides `probabilities_` — the outlier likelihood. This is stored on each utterance's `outlier_score` column and feeds into A1 (relevance filtering) in Block 7.

#### 6.5 Failure Handling

| Failure | Behavior |
|---|---|
| 0 segments | Skip clustering, return empty result |
| 1 segment | Single topic created, no clustering needed |
| All segments outliers | Topics table empty, all utterances get `outlier_score ≈ 1.0` |
| BERTopic crash | T3 retries once; on final failure, session marked `failed` |
| VRAM exhaustion | Reduce batch size; log warning |

### 7. Test Specification

| ID | Type | Given | When | Then |
|---|---|---|---|---|
| T30.1 | I | 50 segments across 3 topics | Cluster | Produces topics; each segment assigned a topic_id or marked outlier |
| T30.2 | V | S05 labeled data (30 lectures) with ground-truth topics | Cluster segment embeddings | Purity > 0.70 against S05 topic labels |
| T30.3 | V | Synthetic transcript covering 2 distinct topics (e.g., ML + Data Structures) | Cluster | ≥ 2 clusters produced (FR-5.8) |
| T30.4 | I | Segments from subject A and subject B loaded | Cluster for subject A | No cross-subject vectors retrieved; topics scoped to subject A only |
| T30.5 | I | Segments clustered, HDBSCAN assigned noise labels | Persist | `outlier_score` written to `utterances.outlier_score` for all utterances in session |
| T30.6 | P | 31,000 segment embeddings | Cluster | Completes in < 5 minutes |
| T30.7 | I | Segments already assigned topics | Verify | Topic assignments are contiguous within a segment (inherited from S28) |

**Fixtures:**
- `fixture_50_segments_3topics` — 50 segments with 3 ground-truth topic labels
- `fixture_s05_labeled_segments` — S05 data with segment-level topic annotations
- `fixture_2topic_transcript` — Synthetic transcript covering ML and Data Structures
- `fixture_bertopic_model` — Pre-fitted BERTopic model for testing persistence

### 8. Observability

| Type | Name | Details |
|---|---|---|
| Metric | `clustering_topics_count` | Histogram of topics per session |
| Metric | `clustering_outliers_count` | Histogram of outlier segments per session |
| Metric | `clustering_purity` | Gauge of purity on S05 data |
| Metric | `clustering_duration_seconds` | Histogram of clustering time |
| Span | `task.T3_cluster_segments` | Full T3 task trace |
| Span | `clustering.bertopic_fit` | BERTopic fit_transform trace |
| Log | `clustering.subject_scoped` | INFO confirming subject isolation |

### 9. Rollback

- **Code:** Remove `src/ml/clustering/tasks.py` and `src/ml/clustering/schemas.py`.
- **Docker:** No new services.
- **Data:** `DROP TABLE topics;` — cascading to segments (topic_id FK). Segments remain but lose topic assignments.
- **Feature flag:** `CLUSTERING_ENABLED` env var. Set `false` to skip T3 in flow.

### 10. Exit Checklist

- [ ] Clustering produces topics; each segment assigned a topic or marked outlier
- [ ] Purity > 0.70 against S05 topic labels (production target)
- [ ] A session covering two distinct topics yields ≥ 2 clusters (FR-5.8)
- [ ] Clustering scoped strictly within one subject; no cross-subject vectors retrieved
- [ ] Outlier scores persisted on utterances
- [ ] Clustering 31k vectors completes in < 5 min
- [ ] Topic assignments are contiguous within a segment (inherited from S28)
- [ ] All tests T30.1–T30.7 pass

**Closing condition:** Topics discovered within a subject at target purity, with outlier scores available downstream.

---

## S31 — Topic Labelling & Keyword Extraction

### 1. Stage Identity

| Field | Value |
|---|---|
| **ID** | S31 |
| **Name** | Topic Labelling & Keyword Extraction |
| **Block** | B4 |
| **Owner** | ML/Agents |
| **Estimate** | 2–3 days |

### 2. Context

S30 produces unlabeled topic clusters. S31 makes them human-meaningful: c-TF-IDF + KeyBERT extracts side keywords per cluster, and an LLM generates descriptive labels from each cluster's top-N representative utterances plus keywords. Labels are human-editable via API and preserved across re-clustering (S32). A labelling failure degrades gracefully to a placeholder label — the pipeline continues.

**Preceding stages:** S30 (topics with centroids, no labels yet).

### 3. Dependencies

| Dependency | Type | Notes |
|---|---|---|
| S30 | Upstream | Topics with centroids |
| c-TF-IDF | Algorithm | Class-based TF-IDF for keyword extraction |
| KeyBERT | Library | Keyword extraction from cluster documents |
| LLM | External | For label generation (Tier 1–3 from ADR-016) |
| ADR-016 | Decision | Hybrid LLM ladder |

### 4. Requirements Traced

| ID | Source | Verbatim |
|---|---|---|
| FR-2.7 | SRS v1.0 | Topic labels |
| ML-6 | SRS v1.0 | Keyword extraction |
| ML-8 | SRS v1.0 | LLM-based topic labelling |

### 5. Interface Contracts

#### 5.1 Keyword Extraction

```python
# src/ml/clustering/keywords.py
def extract_keywords(
    topic_id: uuid.UUID,
    utterance_texts: list[str],
    n_keywords: int = 10,
) -> list[KeywordResult]:
    """Extract keywords using c-TF-IDF + KeyBERT.

    Steps:
    1. Concatenate all utterance texts in cluster into single document
    2. Apply c-TF-IDF (class-based TF-IDF)
    3. Use KeyBERT to extract top-N keywords from c-TF-IDF output
    4. Return keywords with scores
    """
    ...


@dataclass
class KeywordResult:
    keyword: str
    score: float
```

#### 5.2 LLM Labelling

```python
# src/ml/clustering/labelling.py
LABELLING_PROMPT_V1 = """You are given a topic cluster from a university lecture transcript.

Top representative utterances:
{utterances}

Top keywords: {keywords}

Generate a short, descriptive label (max 10 words) for this topic.
The label should be specific enough to distinguish it from other topics in the same subject.

Label:"""


async def generate_topic_label(
    utterances: list[str],
    keywords: list[str],
    llm_client: LLMClient,
    prompt_version: str = "v1",
) -> str:
    """Generate a topic label using LLM from top-N utterances and keywords.

    Falls back to placeholder on LLM failure.
    """
    ...
```

#### 5.3 Label Edit API

```python
# src/api/routes/topics.py (NEW)
@router.put("/subjects/{subject_id}/topics/{topic_id}/label")
async def update_topic_label(
    subject_id: uuid.UUID,
    topic_id: uuid.UUID,
    body: TopicLabelUpdate,
) -> TopicResponse:
    """Update topic label (user edit). Preserved across re-clustering."""
    ...


class TopicLabelUpdate(BaseModel):
    label: str = Field(min_length=1, max_length=200)
```

### 6. Implementation Notes

#### 6.1 c-TF-IDF + KeyBERT Pipeline

```python
from bertopic import BERTopic
from sklearn.feature_extraction.text import CountVectorizer

# c-TF-IDF: BERTopic's built-in
vectorizer = CountVectorizer(stop_words="english", ngram_range=(1, 2))
topic_model = BERTopic(..., vectorizer_model=vectorizer)

# After clustering, extract keywords:
topic_info = topic_model.get_topic(topic_id)
# Returns list of (keyword, score) tuples
```

#### 6.2 LLM Prompt Versioning

The prompt is versioned (`v1`) to track label quality improvements. Prompt text is stored in code, not external config, to ensure reproducibility.

#### 6.3 User-Edited Label Preservation

```python
# When updating topic label:
async def update_topic_label(topic_id, label, is_user_edited=True):
    await session.execute(
        text("""
            UPDATE topics
            SET label = :label, is_user_edited = TRUE, updated_at = now()
            WHERE id = :topic_id
        """),
        {"topic_id": topic_id, "label": label},
    )
```

In S32 (re-clustering), labels with `is_user_edited = TRUE` are never overwritten.

#### 6.4 Single-Member Cluster Handling

When a cluster has only 1 utterance:
- Keywords extracted from that single document
- LLM receives 1 utterance (still works)
- Label quality may be lower; logged as warning

#### 6.5 Failure Handling

| Failure | Behavior |
|---|---|
| LLM unreachable | Placeholder label `"Topic {topic_id[:8]}"`, pipeline continues |
| c-TF-IDF returns 0 keywords | Keywords list empty, LLM label-only |
| Single-member cluster | Works but lower quality; log warning |
| LLM returns empty/invalid label | Retry once; then placeholder |

### 7. Test Specification

| ID | Type | Given | When | Then |
|---|---|---|---|---|
| T31.1 | V | 20 clusters with utterance texts | Extract keywords, human review | ≥ 80% of clusters have keywords judged relevant |
| T31.2 | M | 20 clusters with keywords and utterance texts | LLM generates labels, human review | ≥ 80% of labels judged accurate |
| T31.3 | I | Topic with `is_user_edited = TRUE` | Re-clustering runs (S32) | User-edited label preserved, not overwritten |
| T31.4 | U | Single-member cluster (1 utterance) | Extract keywords + generate label | No error; keywords and label returned (may be lower quality) |
| T31.5 | I | LLM client raises `ConnectionError` | Generate label | Placeholder label assigned; pipeline continues without error |

**Fixtures:**
- `fixture_20_clusters` — 20 topic clusters with utterance texts and keywords
- `fixture_single_member_cluster` — Cluster with 1 utterance
- `fixture_llm_client_mock` — Mock LLM client that raises `ConnectionError`
- `fixture_user_edited_topic` — Topic with `is_user_edited = TRUE`

### 8. Observability

| Type | Name | Details |
|---|---|---|
| Metric | `labelling_keywords_extracted` | Histogram of keywords per topic |
| Metric | `labelling_llm_latency_seconds` | Histogram of LLM label generation time |
| Metric | `labelling_llm_failures` | Counter of LLM failures (placeholder used) |
| Log | `labelling.placeholder_used` | WARNING when placeholder label used |
| Log | `labelling.user_label_preserved` | INFO when user-edited label preserved |

### 9. Rollback

- **Code:** Remove `src/ml/clustering/keywords.py`, `src/ml/clustering/labelling.py`, `src/api/routes/topics.py`.
- **Data:** `UPDATE topics SET label = NULL, keywords = NULL, is_user_edited = FALSE;` — labels removed but topics remain.
- **Feature flag:** `TOPIC_LABELLING_ENABLED` env var. Set `false` to skip labelling; topics remain unlabeled.

### 10. Exit Checklist

- [ ] Extracted keywords judged relevant by human review on 20 clusters (≥ 80% acceptable)
- [ ] LLM topic labels judged accurate on 20 clusters (≥ 80%)
- [ ] User label edit persists and is not overwritten by re-clustering
- [ ] Labelling handles a single-member cluster without error
- [ ] Labelling failure leaves a placeholder label; pipeline continues
- [ ] All tests T31.1–T31.5 pass

**Closing condition:** Topics carry human-meaningful labels and keywords.

---

## S32 — Cross-Session Topic Identity

### 1. Stage Identity

| Field | Value |
|---|---|
| **ID** | S32 |
| **Name** | Cross-Session Topic Identity |
| **Block** | B4 |
| **Owner** | ML |
| **Estimate** | 4–5 days |

### 2. Context

Topics must accumulate across sessions within a subject. When a new session is processed, each new segment's embedding is matched against the subject's existing topic centroids via pgvector nearest-centroid search. Above threshold → link to existing topic (FR-5.4); below → create new topic (FR-5.5). Centroids update incrementally after each session. A full re-cluster flow runs every N sessions (default 10, tighter for sessions 2–5 per §12.5 cold start) to consolidate drift. This is the stage that makes "same topic taught across 3 sessions = 1 topic" (AC-4) work.

**Preceding stages:** S31 (topics with labels and keywords).

### 3. Dependencies

| Dependency | Type | Notes |
|---|---|---|
| S31 | Upstream | Topics with labels and keywords |
| S30 | Upstream | BERTopic pipeline for full re-cluster |
| S29 | Upstream | Segmentation algorithm |
| ADR-010 | Decision | Subject-scoped topic identity |
| pgvector | Extension | Nearest-centroid search with HNSW index |

### 4. Requirements Traced

| ID | Source | Verbatim |
|---|---|---|
| FR-5.3 | SRS v1.0 | Topic identity across sessions |
| FR-5.4 | SRS v1.0 | Link to existing topic |
| FR-5.5 | SRS v1.0 | Create new topic |
| FR-5.10 | SRS v1.0 | Incremental centroid update |
| FR-5.11 | SRS v1.0 | Full re-cluster flow |
| ADR-010 | Architecture | Subject-scoped topic identity |
| AC-4 | Acceptance | Same topic across 3 sessions = 1 topic |

### 5. Interface Contracts

#### 5.1 Centroid Matching Query

```python
# src/ml/clustering/cross_session.py
async def match_segment_to_topic(
    subject_id: uuid.UUID,
    segment_embedding: list[float],
    threshold: float = 0.75,
) -> MatchResult:
    """Nearest-centroid match against subject's existing topics.

    Query: SELECT id, centroid <=> :embedding AS distance
           FROM topics WHERE subject_id = :subject_id
           ORDER BY distance ASC LIMIT 1

    If distance < (1 - threshold): link to existing topic
    If distance >= (1 - threshold): create new topic
    """
    ...


@dataclass
class MatchResult:
    matched: bool
    topic_id: uuid.UUID | None  # None if new topic
    distance: float
    cosine_similarity: float  # 1 - distance
    is_new: bool
```

#### 5.2 Link/Create Logic

```python
async def process_segment_topics(
    subject_id: uuid.UUID,
    session_id: uuid.UUID,
    segments: list[SegmentResult],
    segment_embeddings: list[list[float]],
    threshold: float = 0.75,
) -> list[SegmentTopicAssignment]:
    """For each segment, match or create topic.

    1. For each segment embedding:
       a. Nearest-centroid search against subject's topics
       b. If cosine_similarity >= threshold: link (FR-5.4)
       c. If cosine_similarity < threshold: create new topic (FR-5.5)
    2. Update centroids incrementally for linked topics
    3. Return assignments
    """
    ...
```

#### 5.3 Incremental Centroid Update

```python
async def update_centroid(
    topic_id: uuid.UUID,
    new_segment_embedding: list[float],
) -> None:
    """Incremental centroid update after linking a new segment.

    New centroid = weighted average of existing centroid and new embedding,
    weighted by segment_count.

    centroid_new = (centroid_old * count + new_embedding) / (count + 1)
    """
    ...
```

#### 5.4 Re-Cluster Flow

```python
@flow(name="recluster_subject")
async def recluster_subject(
    subject_id: uuid.UUID,
    trigger_reason: str = "periodic",
) -> ReclusterResult:
    """Full re-cluster for a subject.

    Triggered every N sessions (default 10).
    Tighter for sessions 2-5 (every 2 sessions, per §12.5 cold start).

    Preserves user-edited labels (S31).
    """
    ...


# Re-cluster trigger logic:
def should_recluster(session_number: int, recluster_interval: int = 10) -> bool:
    """Determine if full re-cluster should run.

    Cold start: sessions 2-5 → recluster every 2 sessions
    Normal: recluster every recluster_interval sessions
    """
    if session_number <= 5:
        return session_number % 2 == 0  # Sessions 2, 4
    return session_number % recluster_interval == 0
```

### 6. Implementation Notes

#### 6.1 Threshold Sensitivity

The matching threshold (default 0.75 cosine similarity) is tuned:
- **Too low:** Different topics merged incorrectly
- **Too high:** Same topic split across multiple entries
- Tuned against S05 labels; value justified in evaluation report

#### 6.2 Cold Start (§12.5)

Sessions 2–5 have very few existing topics. Re-clustering is more frequent to consolidate quickly:
- Session 2: recluster (1 existing topic)
- Session 4: recluster (2–3 existing topics)
- Session 10+: recluster every 10 sessions

#### 6.3 Re-Cluster Label Preservation

```python
async def recluster_preserve_labels(
    subject_id: uuid.UUID,
    all_embeddings: list[list[float]],
    all_segment_ids: list[uuid.UUID],
) -> ReclusterResult:
    """Full re-cluster that preserves user-edited labels.

    Process:
    1. Re-run BERTopic on all segment embeddings
    2. For each new topic, find best-matching existing topic by centroid
    3. If match found and existing topic has is_user_edited=TRUE:
       - Inherit the user-edited label
       - Do not overwrite with LLM label
    4. For unmatched new topics: generate fresh labels (S31)
    """
    ...
```

#### 6.4 Subject Isolation

Matching queries **never** cross subject boundaries. Enforced by:
1. `WHERE subject_id = :subject_id` on all topic queries
2. pg_partman partition key on `topics` table
3. RLS policies (ADR-013)

#### 6.5 Failure Handling

| Failure | Behavior |
|---|---|
| pgvector query fails | Retry once; on failure, create new topic (safe default) |
| Centroid update fails | Log error, topic centroid stale but operational |
| Re-cluster fails | Session topics remain as-is; next session may trigger again |
| Threshold too aggressive | All segments create new topics; logged as warning |

### 7. Test Specification

| ID | Type | Given | When | Then |
|---|---|---|---|---|
| T32.1 | V | 3 separate sessions teaching "Linear Algebra" with same topic | Process all 3 sessions | 1 topic in `topics` table with `segment_count ≥ 3`, not 3 separate topics (AC-4) |
| T32.2 | V | Existing topics: "ML", "Data Structures". New session introduces "Quantum Computing" | Match new segments | "Quantum Computing" creates new topic (not force-matched to existing) |
| T32.3 | I | Session 1 created 2 topics. Session 2 links 1 new segment to existing topic | Verify | Centroid updated: `(old_centroid * 1 + new_embedding) / 2`; topic segment_count incremented |
| T32.4 | I | Topic with `is_user_edited = TRUE` and custom label | Full re-cluster | User-edited label preserved; not overwritten by LLM |
| T32.5 | I | Topics for subject A and subject B | Match segments for subject A | Only subject A topics in results; no cross-subject leakage |
| T32.6 | V | S05 labels, threshold sweep (0.60–0.90) | Evaluate P_k on topic matching | Threshold 0.75 ± 0.05 chosen; justified against S05 labels |
| T32.7 | P | 50 existing topics, 10 new segments | Match all segments | Completes in < 1 second |

**Fixtures:**
- `fixture_3_sessions_same_topic` — 3 sessions teaching the same topic
- `fixture_new_topic_session` — Session with a genuinely new topic
- `fixture_user_edited_topic` — Topic with `is_user_edited = TRUE`
- `fixture_two_subjects` — Two subjects with separate topic sets
- `fixture_threshold_sweep` — Pre-computed centroid distances for threshold analysis

### 8. Observability

| Type | Name | Details |
|---|---|---|
| Metric | `cross_session_matched` | Counter of segment-to-topic matches |
| Metric | `cross_session_new_topics` | Counter of new topics created |
| Metric | `cross_session_match_distance` | Histogram of cosine distances for matches |
| Metric | `cross_session_recluster_runs` | Counter of full re-cluster runs |
| Span | `cross_session.match_segment` | Per-segment matching trace |
| Span | `cross_session.recluster` | Full re-cluster trace |
| Log | `cross_session.cold_start_recluster` | INFO when cold-start recluster triggers |

### 9. Rollback

- **Code:** Remove `src/ml/clustering/cross_session.py`. Topics table remains but no cross-session linking occurs.
- **Data:** `UPDATE segments SET topic_id = NULL; UPDATE topics SET segment_count = 0, utterance_count = 0;` — unlinks but preserves topics.
- **Docker:** No changes.
- **Feature flag:** `CROSS_SESSION_IDENTITY_ENABLED` env var. Set `false` to disable cross-session matching; each session creates independent topics.

### 10. Exit Checklist

- [ ] A topic taught across three separate sessions is recognised as one topic, not three (AC-4)
- [ ] A genuinely new topic creates a new partition rather than being force-matched
- [ ] Centroids update incrementally and correctly after each session
- [ ] Full re-cluster preserves user-edited labels (S31)
- [ ] Matching queries never cross subject boundaries
- [ ] Threshold sensitivity analysed; chosen value justified against S05 labels
- [ ] Matching a session's segments against 50 existing topics in < 1s
- [ ] All tests T32.1–T32.7 pass

**Closing condition:** Topic identity accumulates correctly across a semester within a subject.

---

## Appendix A — New Database Objects Summary

| Object | Type | Stage | Description |
|---|---|---|---|
| `topics` | Table | S30 | Topic clusters with centroids, labels, keywords |
| `topics_centroid_idx` | HNSW index | S30 | Nearest-centroid search for matching |
| `topics_session_id_fk` | FK | S30 | Links topic to creating session |

## Appendix B — New Files Summary

| File | Stage | Description |
|---|---|---|
| `src/ml/embedding/__init__.py` | S25 | Embedding package |
| `src/ml/embedding/client.py` | S25 | TEI/sentence-transformers client |
| `src/ml/embedding/schemas.py` | S25 | Pydantic schemas |
| `src/ml/embedding/versioning.py` | S25 | Version registry |
| `src/ml/embedding/backfill.py` | S25 | Backfill flow skeleton |
| `src/ml/embedding/windowing.py` | S26 | Context-window construction |
| `src/ml/embedding/pipeline.py` | S26 | Windowed embedding pipeline |
| `src/ml/embedding/flows.py` | S27 | Prefect flows (T1) |
| `src/ml/clustering/__init__.py` | S28 | Clustering package |
| `src/ml/clustering/segmentation.py` | S28 | TextTiling segmentation |
| `src/ml/clustering/schemas.py` | S30 | Clustering Pydantic schemas |
| `src/ml/clustering/tasks.py` | S30 | T3 Prefect task |
| `src/ml/clustering/keywords.py` | S31 | c-TF-IDF + KeyBERT |
| `src/ml/clustering/labelling.py` | S31 | LLM label generation |
| `src/ml/clustering/cross_session.py` | S32 | Centroid matching + re-cluster |
| `src/api/routes/topics.py` | S31 | Topic label edit API |
| `scripts/s26_window_benchmark.py` | S26 | Windowed vs isolated benchmark |
| `scripts/s29_segmentation_eval.py` | S29 | Segmentation evaluation |

## Appendix C — Docker Services Added

| Service | Stage | Image | Port | Memory |
|---|---|---|---|---|
| `tei` | S25 | `ghcr.io/huggingface/text-embeddings-inference:cpu-1.5` | 80 (internal) | 2G |
| `prefect-server` | S27 | `prefecthq/prefect:3-latest` | 4200 | 1G |

## Appendix D — Config Keys Added

```yaml
# config/models.yaml additions:
embedding_versions:
  active: "qwen3-0.6b-v1"
  registry: { ... }

embedding:
  window_size: 5
  window_stride: 1
  min_window: 1
```

## Appendix E — Environment Variables

| Variable | Default | Stage | Purpose |
|---|---|---|---|
| `EMBEDDING_SERVICE_ENABLED` | `true` | S25 | Toggle embedding service |
| `EMBEDDING_WINDOW_SIZE` | `5` | S26 | Override window size |
| `PREFECT_ENABLED` | `true` | S27 | Toggle Prefect orchestration |
| `SEGMENTATION_ENABLED` | `true` | S28 | Toggle segmentation |
| `CLUSTERING_ENABLED` | `true` | S30 | Toggle BERTopic clustering |
| `TOPIC_LABELLING_ENABLED` | `true` | S31 | Toggle labelling |
| `CROSS_SESSION_IDENTITY_ENABLED` | `true` | S32 | Toggle cross-session matching |
| `TOPIC_MATCH_THRESHOLD` | `0.75` | S32 | Cosine similarity threshold |
| `RECLUSTER_INTERVAL` | `10` | S32 | Sessions between full re-clusters |
