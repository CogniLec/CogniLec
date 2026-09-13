# S27 — Prefect Setup & Embedding Task (T1)
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Deploy Prefect server with worker pools (`ml-pool`, `llm-pool`), implement the `process_session` flow with NFR-R3 assertion gate at entry, Task T1 `embed_utterances` with caching, and event-driven triggering on `session.transcribed`.

**Component Boundaries:**
- **Allowed:** `src/flows/`, `src/tasks/`, Prefect deployment configs, `tests/test_prefect_embedding.py`
- **Off-limits:** Embedding client (S25), windowing (S26), segmentation (S28), clustering (S30)

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| Prefect | 2.x | Workflow orchestration |
| Prefect Server | 2.x | Self-hosted orchestration |
| SQLAlchemy | 2.0.52 | Session status checks |
| Redis | 7.x | Prefect result cache backend |
| pytest | 8.x | Integration tests |

---

### 2. State Machine & Domain Schemas

**Flow State:**
```
PENDING → RUNNING → COMPLETED
            ↓
         FAILED → RETRYING → RUNNING
```

**Prefect Worker Pools:**
```
ml-pool:  embedding, segmentation, clustering tasks
llm-pool: LLM inference tasks (S31 labelling)
```

**Pydantic Models:**
```python
# src/flows/process_session.py
from prefect import flow, task, get_run_logger
from prefect.cache_policies import INPUTS, INPUTS + METADATA

class SessionInput(BaseModel):
    session_id: UUID
    subject_id: UUID
    embed_model_ver: str

@task(
    name="embed_utterances",
    retries=3,
    retry_delay_seconds=30,
    cache_key_fn=lambda ctx: INPUTS + METADATA,
    cache_expiration=timedelta(hours=24),
    tags=["ml-pool"],
)
async def embed_utterances(
    session_id: UUID,
    subject_id: UUID,
    embed_model_ver: str,
) -> int:
    """T1: Embed all utterances for a session. Cached on (session_id, embed_model_ver)."""

@flow(
    name="process_session",
    tags=["ml-pool"],
    retry_exceptions=[ConnectionError, TimeoutError],
)
async def process_session(input: SessionInput) -> dict:
    """
    Main session processing flow.
    Entry gate: session status MUST be 'transcribed' (NFR-R3).
    """
```

**NFR-R3 Assertion Gate:**
```python
@flow(name="process_session")
async def process_session(input: SessionInput) -> dict:
    logger = get_run_logger()

    # NFR-R3: Session must be in 'transcribed' status
    session = await session_repo.get(input.session_id)
    if session.status != SessionStatus.TRANSCRIBED:
        raise ValueError(
            f"NFR-R3 violated: session {input.session_id} "
            f"has status '{session.status}', expected 'transcribed'"
        )

    # Transition to processing
    await lifecycle.transition(input.session_id, SessionStatus.PROCESSING)

    # Run T1
    utt_count = await embed_utterances(
        input.session_id,
        input.subject_id,
        input.embed_model_ver,
    )

    return {"session_id": str(input.session_id), "utterances_embedded": utt_count}
```

**Cache Policy:**
```python
# Cache key = (session_id, embed_model_ver)
# If same session_id + same embed_model_ver → cache hit, no re-embed
# If same session_id + different embed_model_ver → cache miss, re-embed
# This ensures model version changes invalidate the cache
```

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Deploy Prefect server in Docker Compose | `prefect server health-check` returns 200 |
| 2 | Create `ml-pool` and `llm-pool` worker pools | `prefect work-pool ls` shows both pools |
| 3 | Implement `embed_utterances` task (T1) | Task can be called with session_id |
| 4 | Implement `process_session` flow with NFR-R3 gate | T27.2 passes |
| 5 | Wire `session.transcribed` event to flow trigger | T27.1 passes |
| 6 | Implement caching on (session_id, embed_model_ver) | T27.3, T27.4 pass |
| 7 | Implement idempotency and retry logic | T27.5 passes |
| 8 | Implement failure marking | T27.6 passes |

**Atomic Sub-tasks:**
1. Prefect server deployment
2. Worker pool creation
3. `embed_utterances` task with caching
4. `process_session` flow with NFR-R3 gate
5. Event-driven trigger on `session.transcribed`
6. Cache invalidation on model version change
7. Idempotency guard for duplicate task runs
8. Failure propagation to session status

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| Session not in `transcribed` status | Flow refuses to start (NFR-R3) |
| Worker killed mid-task | Prefect retries task; idempotent re-embed |
| Duplicate task run from event replay | Cache hit returns previous result; no duplicate rows |
| Flow failure | Session marked `failed`, event emitted |
| Embedding client unavailable | Task retries with backoff; session eventually fails |
| Cache backend (Redis) unavailable | Tasks run without cache; warn in logs |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Flow pattern: Prefect `@flow` with entry guards
- Task pattern: Prefect `@task` with caching and retries
- Event pattern: `session.transcribed` triggers flow
- Gate pattern: NFR-R3 assertion at flow entry

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase
- Files: snake_case (`process_session.py`, `embed_utterances.py`)
- Prefect task names: verb_noun (`embed_utterances`)

**Code Splitting Metrics:**
- Max function length: 40 lines
- Max file length: 300 lines

**Type Safety:**
- All function signatures typed with Pydantic v2 models
- `from __future__ import annotations` in all files

---

### 5. API & Interface Contracts

**Prefect Deployment Config:**
```yaml
# deployments/process_session.yaml
name: process-session
entrypoint: src/flows/process_session.py:process_session
parameters:
  input:
    session_id: "00000000-0000-0000-0000-000000000000"
    subject_id: "00000000-0000-0000-0000-000000000000"
    embed_model_ver: "qwen3-0.6b-v1"
work_pool:
  name: ml-pool
  type: process
schedule: null  # Event-driven, not scheduled
```

**Event Trigger:**
```python
# src/events/session_transcribed_handler.py
async def on_session_transcribed(event: SessionTranscribedEvent) -> None:
    """Handle session.transcribed event by triggering process_session flow."""
    from prefect.deployments import run_deployment

    await run_deployment(
        name="process-session",
        parameters={
            "input": {
                "session_id": str(event.session_id),
                "subject_id": str(event.subject_id),
                "embed_model_ver": event.embed_model_ver,
            }
        },
    )
```

**Task Interface:**
```python
@task(
    name="embed_utterances",
    retries=3,
    retry_delay_seconds=30,
    cache_key_fn=lambda ctx: INPUTS + METADATA,
    cache_expiration=timedelta(hours=24),
)
async def embed_utterances(
    session_id: UUID,
    subject_id: UUID,
    embed_model_ver: str,
) -> int:
    """
    T1: Embed all utterances for a session.

    Cache key = (session_id, embed_model_ver).
    Same session + same version → cache hit.
    Different version → cache miss, re-embed.

    Returns count of utterances embedded.
    """
    logger = get_run_logger()

    # Fetch utterances
    utterances = await utterance_repo.get_by_session(subject_id, session_id)
    if not utterances:
        logger.warning(f"No utterances found for session {session_id}")
        return 0

    # Build windows (S26)
    windows = window_builder.build_windows(utterances)

    # Embed with version stamp
    for window in windows:
        emb = await embedding_client.embed_single(
            " ".join(window.window_texts),
            task_mode=EmbeddingTaskMode.RETRIEVAL,
        )
        await utterance_repo.update_embedding(subject_id, window.utterance_id, emb, embed_model_ver)

    logger.info(f"Embedded {len(windows)} utterances for session {session_id}")
    return len(windows)
```

**Event Contract:**
```json
{
  "event": "session.transcribed",
  "session_id": "uuid",
  "subject_id": "uuid",
  "embed_model_ver": "qwen3-0.6b-v1",
  "timestamp": "2026-09-12T10:00:00Z"
}
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Default |
|----------|------|-------------|---------|
| `PREFECT_API_URL` | string | Prefect server URL | `http://prefect:4200/api` |
| `PREFECT_SERVER_HOST` | string | Prefect server host | `0.0.0.0` |
| `PREFECT_SERVER_PORT` | int | Prefect server port | `4200` |
| `PREFECT_RESULT_BACKEND` | string | Result cache backend | `redis://redis:6379/0` |
| `PREFECT_WORKER_POOLS` | string | Comma-separated pool names | `ml-pool,llm-pool` |
| `EMBEDDING_CACHE_EXPIRY_HOURS` | int | Cache TTL for T1 | `24` |

**Third-Party Integration Contracts:**
- Prefect Server: self-hosted, Docker Compose
- Redis: result caching backend
- Session lifecycle (S23): status checks and transitions

**Version Pins:**
- Prefect >= 2.19.0
- Redis >= 7.0

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T27.1 | I | `pytest tests/test_prefect_embedding.py::test_flow_triggers_on_event -v` | Flow triggers automatically on `session.transcribed` |
| T27.2 | I | `pytest tests/test_prefect_embedding.py::test_nfr_r3_gate -v` | Flow refuses to start if session status is not `transcribed` |
| T27.3 | I | `pytest tests/test_prefect_embedding.py::test_cache_hit -v` | Re-running the flow reuses cached T1 results |
| T27.4 | I | `pytest tests/test_prefect_embedding.py::test_cache_invalidation -v` | Changing `embed_model_ver` invalidates cache |
| T27.5 | I | `pytest tests/test_prefect_embedding.py::test_worker_kill_idempotency -v` | Worker killed mid-task → task retried, no duplicate rows |
| T27.6 | I | `pytest tests/test_prefect_embedding.py::test_failure_marks_session -v` | Flow failure marks session `failed` and emits event |

**Test Case Details (Given/When/Then):**

**T27.1 — Flow triggers on session.transcribed**
- **Given:** a session in `transcribed` status
- **When:** a `session.transcribed` event is emitted
- **Then:** the `process_session` flow is triggered within 10 seconds

**T27.2 — NFR-R3 gate rejects non-transcribed sessions**
- **Given:** a session in `processing` status
- **When:** `process_session` flow is triggered manually
- **Then:** flow raises `ValueError` with NFR-R3 message; session status unchanged

**T27.3 — Cached T1 results reused**
- **Given:** a session that has been processed with model v1
- **When:** `process_session` is re-triggered with the same `embed_model_ver=v1`
- **Then:** T1 task is skipped (cache hit); utterance count matches; no DB writes

**T27.4 — Version change invalidates cache**
- **Given:** a session processed with model v1
- **When:** `process_session` is triggered with `embed_model_ver=v2`
- **Then:** T1 task runs (cache miss); utterances re-embedded with v2 stamps

**T27.5 — Worker kill recovery, no duplicates**
- **Given:** a running T1 task with 500 utterances partially embedded
- **When:** the worker process is killed
- **Then:** Prefect retries the task; final utterance count is correct; no duplicate rows

**T27.6 — Failure marks session as failed**
- **Given:** a session in `processing` status
- **When:** the flow encounters an unrecoverable error
- **Then:** session status transitions to `failed`; `session.failed` event emitted

**Verification Commands:**
```bash
docker compose up -d prefect-server redis && \
sleep 30 && \
curl -f http://localhost:4200/api/health && \
uv run pytest tests/test_prefect_embedding.py -v -k "S27 or prefect" && \
uv run mypy --strict src/flows/ src/tasks/ && \
uv run ruff check src/flows/ src/tasks/
```

**Exit Criteria:**
- [ ] T27.1 passes — flow triggers on `session.transcribed`
- [ ] T27.2 passes — NFR-R3 gate enforced
- [ ] T27.3 passes — cached T1 results reused
- [ ] T27.4 passes — version change invalidates cache
- [ ] T27.5 passes — worker kill recovery, no duplicates
- [ ] T27.6 passes — failure marks session and emits event
- [ ] Pipeline is event-driven, cached, and idempotent

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- Prefect cache key must include `embed_model_ver`; without it, model changes won't invalidate cache
- NFR-R3 check must happen inside the flow, not at event handler level — status can change between event emit and flow start
- Redis cache eviction can cause re-embedding; set TTL > expected session lifetime
- Idempotency requires `ON CONFLICT DO NOTHING` in DB writes, not just cache

**Fallback Instructions:**
- If Prefect server is down: queue events in Redis; process when Prefect recovers
- If cache backend fails: tasks run without cache; log warning; no data loss
- If worker pool is full: tasks queue; monitor `prefect work-pool preview ml-pool`

**Rollback Procedure:**
- Stop Prefect: `docker compose stop prefect-server`
- No schema migrations to revert (flow state is in Prefect DB, can be cleared)
- Session status remains as-is; manually reset to `transcribed` if needed
- Feature flag: not applicable; removing Prefect deployment stops flows

---

### 9. Observability (if applicable)

**Metrics Added:**
- `prefect_flow_run_total`: counter of flow runs (labels: flow_name, status)
- `prefect_task_run_total`: counter of task runs (labels: task_name, status)
- `prefect_task_cache_hit_total`: counter of cache hits (labels: task_name)
- `prefect_task_duration_seconds`: histogram of task execution time
- `prefect_flow_failure_total`: counter of flow failures (labels: reason)

**Tracing/Logging:**
- Span: `prefect.flow.process_session` with attributes (session_id, subject_id)
- Span: `prefect.task.embed_utterances` with attributes (session_id, cache_hit, utterance_count)
- Log: INFO on flow start, task completion, cache hit/miss
- Log: ERROR on flow failure with full traceback
- Log: WARN on NFR-R3 rejection

**Alerts:**
- Flow failure rate > 10% in 1 hour: pipeline issue
- Task retry count > 5 in 10 minutes: systemic problem
- Worker pool queue depth > 20: scaling needed

---

### 10. Exit Checklist

- [ ] All tests pass (T27.1, T27.2, T27.3, T27.4, T27.5, T27.6)
- [ ] Prefect server running with `ml-pool` and `llm-pool`
- [ ] `process_session` flow with NFR-R3 gate at entry
- [ ] T1 `embed_utterances` cached on `(session_id, embed_model_ver)`
- [ ] Event-driven trigger on `session.transcribed`
- [ ] Flow failure marks session `failed` and emits event
- [ ] Pipeline is event-driven, cached, and idempotent
