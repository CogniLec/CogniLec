# S47 — Full Flow Wiring & Re-Runnability
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Wire tasks T1–T7 into a complete, durable `process_session` flow with per-task cache keys, implement the LangGraph T4 subgraph with session-type routing, add the `uploads.ready` partial re-run path, and emit session lifecycle events.

**Component Boundaries:**
- **Allowed:** `src/pipeline/`, `src/services/session/`, `src/services/cache/`, `src/services/events/`, `src/graph/`, `tests/test_full_flow.py`, `tests/test_partial_rerun.py`, `tests/test_cache_keys.py`
- **Off-limits:** Block 9–13 code, embedding service internals (S48), reranker service (S54), UI components

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| LangGraph | 0.x | Task orchestration and subgraph wiring |
| Redis | 7.x | Cache layer for per-task cache keys |
| Celery | 5.x | Background task execution and durability |
| pytest | 8.x | Integration and end-to-end tests |
| testcontainers | 4.6.x | Container orchestration for tests |

---

### 2. State Machine & Domain Schemas

**Pipeline Flow State Machine:**
```
PENDING → T1(ASR) → T2(TRANSCRIPT_CLEAN) → T3(SEGMENT) → T4(NOTES) → T5(SUMMARY) → T6(FLASHCARDS) → T7(OUTPUT) → COMPLETED
                                    ↓ (error at any task)
                                   FAILED → RESUMABLE (resume from last checkpoint)
                                    ↓ (uploads.ready partial re-run)
                                   PARTIAL → T4(NOTES) → T5(SUMMARY) → T6(FLASHCARDS) → T7(OUTPUT) → COMPLETED
```

**Cache Key Schema:**
```python
# src/services/cache/keys.py
from pydantic import BaseModel


class TaskCacheKey(BaseModel):
    session_id: str
    task_name: str  # T1–T7
    embed_model_ver: str
    prompt_version: str

    def to_redis_key(self) -> str:
        return (
            f"cache:{self.session_id}:{self.task_name}:{self.embed_model_ver}:{self.prompt_version}"
        )


class TaskCacheEntry(BaseModel):
    task_name: str
    cache_key: str
    status: str  # pending | running | completed | failed
    result: dict | None = None
    created_at: str
    updated_at: str
```

**Session State Schema:**
```python
# src/services/session/models.py
from pydantic import BaseModel, Field
from enum import Enum


class SessionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class TaskCheckpoint(BaseModel):
    task_name: str
    status: TaskStatus
    cache_key: str
    error: str | None = None
    started_at: str | None = None
    completed_at: str | None = None


class SessionPipeline(BaseModel):
    session_id: str
    subject_id: str
    status: SessionStatus
    tasks: list[TaskCheckpoint] = Field(default_factory=list)
    created_at: str
    updated_at: str
    event_emitted: bool = False
```

**State Transition Rules:**
- PENDING → RUNNING: when `process_session()` is invoked
- RUNNING → COMPLETED: all tasks T1–T7 complete successfully
- RUNNING → FAILED: any task fails after exhausting retries
- FAILED → COMPLETED: on re-run, resumes from last successful task checkpoint
- PARTIAL → COMPLETED: `uploads.ready` path skips T1–T3, runs T4–T7 using cached results
- Task transitions: each task moves independently, checkpoint written before and after execution

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Define `TaskCacheKey` and `TaskCacheEntry` models | Import succeeds, unit test: key generation |
| 2 | Implement cache key generation in `src/services/cache/keys.py` | T47.2: cache key includes embed_model_ver and prompt_version |
| 3 | Implement `process_session()` flow orchestrator in `src/pipeline/orchestrator.py` | Unit test: flow runs T1–T7 in order |
| 4 | Wire LangGraph T4 subgraph with session_type routing in `src/graph/t4_subgraph.py` | Unit test: audio vs uploads routing |
| 5 | Implement checkpoint persistence after each task | Unit test: checkpoint written to Redis after task completion |
| 6 | Implement resume-from-checkpoint logic in orchestrator | T47.4: resume from each task after simulated failure |
| 7 | Implement `uploads.ready` partial re-run path | T47.5: partial re-run reuses T1–T3 cache |
| 8 | Emit `session.complete` and `session.failed` events | T47.7: events emitted on success and failure |
| 9 | Write end-to-end integration test with real session | T47.1: full flow transcript → notes |
| 10 | Run performance benchmark | T47.6: 60-min lecture < 15 min P90 |

**Atomic Sub-tasks:**
1. Cache key model and generation
2. Pipeline orchestrator with sequential task execution
3. LangGraph T4 subgraph with session_type routing
4. Checkpoint persistence and resume logic
5. Partial re-run path for uploads
6. Event emission on success/failure
7. Integration and performance test suite

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| Worker killed mid-task (T1–T7) | Task checkpoint persists; on restart, orchestrator resumes from last checkpoint |
| Cache key collision (same session, different embed version) | Distinct cache entries per embed_model_ver and prompt_version |
| Redis unavailable | Retry with exponential backoff; after 3 failures, mark session FAILED |
| Task fails after max retries | Mark task FAILED, emit `session.failed`, persist error in checkpoint |
| Partial re-run with missing T1–T3 cache | Fall back to full re-run, log warning |
| Prompt version bump mid-session | Only tasks dependent on prompt recompute; others reuse cache |
| Embedding version bump mid-session | All tasks recompute from T1 (embeddings invalidate downstream) |
| Duplicate session processing | Idempotency key prevents double execution; second invocation returns existing result |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Orchestrator pattern: `process_session()` coordinates task execution
- Checkpoint pattern: each task writes state before and after execution
- Subgraph pattern: LangGraph T4 subgraph encapsulates note generation
- Event emitter pattern: decoupled event emission on state transitions

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase
- Files: snake_case (`orchestrator.py`, `t4_subgraph.py`)
- Functions: snake_case (`process_session`, `resume_task`, `emit_event`)
- Constants: UPPER_SNAKE_CASE (`TASK_NAMES`, `CACHE_TTL_SECONDS`)

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
# src/pipeline/orchestrator.py
async def process_session(session_id: str) -> SessionPipeline:
    """Run the full T1–T7 pipeline for a session."""
    ...


async def resume_session(session_id: str) -> SessionPipeline:
    """Resume a failed session from last checkpoint."""
    ...


async def partial_rerun(session_id: str) -> SessionPipeline:
    """Re-run only T4–T7, reusing T1–T3 cache (uploads path)."""
    ...


# src/graph/t4_subgraph.py
async def t4_subgraph(
    session_type: str,  # "audio" | "uploads"
    context: dict,
) -> dict:
    """LangGraph subgraph for note generation with session_type routing."""
    ...
```

**Event Contracts:**
```json
{
  "event_type": "session.complete",
  "session_id": "sess_abc123",
  "subject_id": "subj_xyz789",
  "completed_tasks": ["T1", "T2", "T3", "T4", "T5", "T6", "T7"],
  "total_duration_ms": 842000,
  "timestamp": "2026-09-12T10:30:00Z"
}
```
```json
{
  "event_type": "session.failed",
  "session_id": "sess_abc123",
  "subject_id": "subj_xyz789",
  "failed_task": "T4",
  "error": "LLM timeout after 3 retries",
  "completed_tasks": ["T1", "T2", "T3"],
  "timestamp": "2026-09-12T10:35:00Z"
}
```

**Redis Cache Schema:**
```
cache:{session_id}:{task_name}:{embed_model_ver}:{prompt_version} → JSON(TaskCacheEntry)
checkpoint:{session_id} → JSON(SessionPipeline)
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Default |
|----------|------|-------------|---------|
| `REDIS_URL` | string | Redis connection URL | `redis://localhost:6379` |
| `CACHE_TTL_SECONDS` | int | Cache entry time-to-live | `86400` |
| `TASK_MAX_RETRIES` | int | Max retries per task | `3` |
| `TASK_RETRY_DELAY_MS` | int | Delay between retries | `5000` |
| `LANGGRAPH_CHECKPOINT_DIR` | string | Directory for LangGraph state | `/tmp/langgraph_checkpoints` |
| `EVENT_BROKER_URL` | string | Event emission endpoint | `redis://localhost:6379` |

**Third-Party Integration Contracts:**
- Redis: checkpoint and cache persistence
- Celery: background task execution (if used for worker management)
- LangGraph: T4 subgraph orchestration

**Version Pins:**
- Redis Python client pinned in `pyproject.toml`
- LangGraph pinned in `pyproject.toml`
- Celery pinned in `pyproject.toml`

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T47.1 | E | `pytest tests/test_full_flow.py::test_full_flow_e2e -v` | Full flow: transcript → notes completed successfully |
| T47.2 | I | `pytest tests/test_cache_keys.py::test_prompt_version_bump_recomputes_only_affected -v` | Prompt version bump recomputes only affected tasks |
| T47.3 | I | `pytest tests/test_cache_keys.py::test_embed_version_bump_recomputes_from_t1 -v` | Embed version bump recomputes from T1 |
| T47.4 | I | `pytest tests/test_full_flow.py::test_resume_from_each_task -v` | Worker killed at T1–T7 → flow resumes correctly |
| T47.5 | I | `pytest test_partial_rerun.py::test_partial_rerun_reuses_cache -v` | Partial re-run reuses T1–T3 cache |
| T47.6 | P | `pytest tests/test_full_flow.py::test_60min_lecture_perf -v` | 60-min lecture processed in < 15 min P90 |
| T47.7 | I | `pytest tests/test_full_flow.py::test_events_emitted_on_success_and_failure -v` | Events emitted on both success and failure |

**Test Case Details (Given/When/Then):**

**T47.1 — Full flow end-to-end**
- **Given:** a real session with recorded lecture audio and transcripts
- **When:** `process_session(session_id)` is called
- **Then:** all tasks T1–T7 complete, session status is COMPLETED, notes are generated with traceable utterances

**T47.2 — Prompt version bump recomputes only affected tasks**
- **Given:** a session with completed pipeline using prompt_version v1
- **When:** prompt_version is bumped to v2 and `resume_session()` is called
- **Then:** only tasks that depend on the prompt recompute; T1–T3 results are reused from cache

**T47.3 — Embed version bump recomputes from T1**
- **Given:** a session with completed pipeline using embed_model_ver v1
- **When:** embed_model_ver is bumped to v2 and `resume_session()` is called
- **Then:** all tasks T1–T7 recompute; no cache entries reused

**T47.4 — Resume from each task after simulated failure**
- **Given:** a session with pipeline running
- **When:** worker is killed at each of T1–T7 in turn, then `resume_session()` is called
- **Then:** flow resumes from the task that was interrupted, completing the remaining tasks

**T47.5 — Partial re-run reuses T1–T3 cache**
- **Given:** a session with T1–T3 completed and cache entries present
- **When:** `partial_rerun(session_id)` is called (uploads path)
- **Then:** T4–T7 execute using cached T1–T3 results, session completes

**T47.6 — Performance benchmark**
- **Given:** a 60-minute recorded lecture session
- **When:** `process_session(session_id)` is called
- **Then:** total processing time is < 15 minutes at P90

**T47.7 — Events emitted on success and failure**
- **Given:** a session that completes successfully and one that fails
- **When:** `process_session()` completes or fails
- **Then:** `session.complete` event is emitted on success, `session.failed` event is emitted on failure, both contain session_id and task status

**Verification Commands:**
```bash
# Full local verification
docker compose up -d redis && \
uv run pytest tests/test_full_flow.py tests/test_cache_keys.py tests/test_partial_rerun.py -v -k "S47" && \
uv run mypy --strict src/pipeline/ src/services/cache/ src/graph/ && \
uv run ruff check src/pipeline/ src/services/cache/ src/graph/
```

**Exit Criteria:**
- [ ] T47.1 passes — full flow completes end-to-end
- [ ] T47.2 passes — prompt version bump recomputes only affected tasks
- [ ] T47.3 passes — embed version bump recomputes from T1
- [ ] T47.4 passes — resume from each task works correctly
- [ ] T47.5 passes — partial re-run reuses T1–T3 cache
- [ ] T47.6 passes — 60-min lecture processed in < 15 min P90
- [ ] T47.7 passes — events emitted on success and failure

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- Redis checkpoint persistence must be atomic — use WATCH/MULTI to prevent race conditions on concurrent session updates
- LangGraph subgraph state serialization can fail on complex objects; ensure all state is JSON-serializable
- Partial re-run path must validate T1–T3 cache integrity before reusing; corrupted cache causes silent data errors
- Event emission must be idempotent — duplicate events on retry should not cause duplicate side effects
- Worker kill during T4 subgraph may leave LangGraph state in inconsistent state; checkpoint must capture subgraph progress

**Fallback Instructions:**
- If Redis is unavailable: log error, mark session FAILED, do not lose data (task results persisted to DB)
- If checkpoint write fails: retry with backoff; after 3 failures, mark session FAILED
- If partial re-run cache is missing: fall back to full re-run, log warning
- If event emission fails: retry with exponential backoff; after 3 failures, log error but do not block pipeline

**Rollback Procedure:**
- Revert code changes: `git revert HEAD` (if only S47 changes)
- Clear corrupted cache: `redis-cli DEL "cache:{session_id}:*"`
- Reset session status: `UPDATE sessions SET status='failed' WHERE id='{session_id}'`
- Force full re-run: call `process_session(session_id)` instead of `resume_session()`
- Feature flag: if partial re-run is unstable, disable via `PARTIAL_RERUN_ENABLED=false`

---

### 9. Observability (if applicable)

**Metrics Added:**
- `pipeline_session_total`: counter of sessions processed (labels: status=completed/failed)
- `pipeline_task_duration_seconds`: histogram of per-task execution time (labels: task_name)
- `pipeline_cache_hit_total`: counter of cache hits (labels: task_name, cache_source)
- `pipeline_resume_total`: counter of resume invocations (labels: from_task)
- `pipeline_partial_rerun_total`: counter of partial re-run invocations
- `pipeline_event_emitted_total`: counter of events emitted (labels: event_type)

**Tracing/Logging:**
- Span: `process_session` with attributes (session_id, subject_id, total_tasks)
- Span: `task.{task_name}` nested under process_session (ASR, transcript_clean, segment, notes, summary, flashcards, output)
- Span: `cache.check` for cache lookup operations
- Span: `cache.write` for cache write operations
- Log: INFO on task completion with duration and cache status
- Log: WARNING on resume from checkpoint with task and error details
- Log: ERROR on pipeline failure with full task status

**Alerts:**
- Pipeline failure rate > 5% over 15 minutes: investigate worker health
- Resume rate > 20% over 15 minutes: investigate task stability
- Cache hit rate < 30% over 1 hour: investigate cache key logic
- Event emission failure rate > 1%: investigate event broker

---

### 10. Exit Checklist

- [ ] All tests pass (T47.1, T47.2, T47.3, T47.4, T47.5, T47.6, T47.7)
- [ ] Cache keys correctly incorporate session_id, embed_model_ver, prompt_version
- [ ] LangGraph T4 subgraph routes correctly based on session_type
- [ ] Partial re-run path reuses T1–T3 cache without re-execution
- [ ] Events emitted on both success and failure
- [ ] Pipeline is durable, resumable, and selectively re-runnable at every stage
- [ ] Performance: 60-min lecture processed in < 15 min P90
