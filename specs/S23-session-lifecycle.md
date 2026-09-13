# S23 — Session Lifecycle State Machine
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Formalize session status transitions into a single, enforced state machine with explicit transition guards, failure marking, retry queue, and the `notes_ready` flag — ensuring no session can be silently half-processed and every failure is visible and recoverable.

**Component Boundaries:**
- **Allowed:** `src/services/session_lifecycle.py`, `src/db/repositories/session_repo.py`, `src/workers/lifecycle_worker.py`, `tests/test_session_lifecycle.py`
- **Off-limits:** ASR workers (S19, S21), note synthesis (S44), embedding (S25)

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| SQLAlchemy | 2.0.52 | ORM models + async queries |
| FastAPI | 0.141.1 | API layer |
| pytest | 8.x | Integration tests |

---

### 2. State Machine & Domain Schemas

**Session Status State Machine:**
```
                    ┌──────────────────────────────────────────┐
                    │                                          │
                    ▼                                          │
               created ──► recording ──► transcribed ──► processing ──► complete
                    │                       │                │
                    │                       │                │
                    ▼                       ▼                ▼
                  failed ◄──────────────────┘────────────────┘
```

**Valid Transitions:**
| From | To | Trigger | Guard |
|------|----|---------|-------|
| `created` | `recording` | First audio chunk received | Session exists, no prior chunks |
| `recording` | `transcribed` | ASR completes, transcript committed | NFR-R3: transcript must be committed before downstream |
| `transcribed` | `processing` | Downstream pipeline starts | NFR-R3: only from `transcribed` |
| `processing` | `complete` | All pipeline stages succeed | notes_ready = true |
| `processing` | `failed` | Any stage fails | error recorded in agent_runs |
| `transcribed` | `failed` | Dual ASR or hallucination detection fails | error recorded |
| `recording` | `failed` | Audio quality below threshold | error recorded |
| Any | `failed` | Unrecoverable error | error recorded, never silent |

**Illegal Transitions (all rejected with ValueError):**
| From | To | Reason |
|------|----|--------|
| `created` | `transcribed` | Must pass through `recording` |
| `created` | `processing` | Must pass through `recording` and `transcribed` |
| `created` | `complete` | Must pass through all intermediate states |
| `complete` | Any | Terminal state, immutable |
| `failed` | Any | Terminal state; must retry from scratch or reprocess |
| `transcribed` | `recording` | Cannot go backwards |
| `processing` | `recording` | Cannot go backwards |
| `processing` | `transcribed` | Cannot go backwards |

**`notes_ready` Flag:**
- Separate from status — can be true/false regardless of `complete`/`failed`
- Set to `true` only when note synthesis completes successfully
- Used by client view to determine if notes are available
- Reset to `false` on reprocessing

**Pydantic Models:**
```python
# src/services/session_lifecycle.py
from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from enum import Enum


class SessionStatus(str, Enum):
    CREATED = "created"
    RECORDING = "recording"
    TRANSCRIBED = "transcribed"
    PROCESSING = "processing"
    COMPLETE = "complete"
    FAILED = "failed"


class TransitionRequest(BaseModel):
    session_id: UUID
    from_status: SessionStatus
    to_status: SessionStatus
    reason: str | None = None


class TransitionResult(BaseModel):
    success: bool
    session_id: UUID
    previous_status: SessionStatus | None
    new_status: SessionStatus | None
    error: str | None = None


class RetryJob(BaseModel):
    session_id: UUID
    subject_id: UUID
    failed_at: datetime
    error: str
    retry_count: int = 0
    max_retries: int = 3
```

**State Transition Rules:**
- All transitions go through `SessionLifecycle.transition()` — single point of enforcement
- Illegal transitions raise `ValueError` with descriptive message
- Failed sessions are added to retry queue automatically
- Retry queue processes with exponential backoff
- `notes_ready` is updated independently via `set_notes_ready()`

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Create `SessionLifecycle` service with transition guards | Illegal transitions rejected |
| 2 | Implement DB-level CHECK constraint for valid status values | SQL constraint enforces enum |
| 3 | Add retry queue mechanism for failed sessions | Failed sessions appear in queue |
| 4 | Implement `notes_ready` flag management | Flag set independently of status |
| 5 | Add concurrent transition handling (optimistic locking) | No split state on concurrent attempts |
| 6 | Wire lifecycle events to downstream pipeline | Pipeline triggers on correct transitions |
| 7 | Run exhaustive transition matrix tests | T23.x pass |

**Atomic Sub-tasks:**
1. `SessionLifecycle` service with transition guards
2. DB CHECK constraint for status enum
3. Retry queue with exponential backoff
4. `notes_ready` flag management
5. Concurrent transition handling (optimistic locking via `updated_at`)
6. Failure event emission

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| Two concurrent transitions attempted | Optimistic lock via `updated_at`; one wins, other retries |
| `failed` session retry exceeds max | Log error, leave in `failed`, alert operator |
| `notes_ready` set on `failed` session | Reject: notes cannot be ready if session failed |
| Transition to same state | No-op, return success (idempotent) |
| Session missing from DB | Raise `SessionNotFoundError` |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- State Machine pattern: explicit states and transitions
- Guard pattern: transition validation in single location
- Retry pattern: exponential backoff with max retries
- Optimistic locking: `updated_at` for concurrent access

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase
- Files: snake_case (`session_lifecycle.py`, `lifecycle_worker.py`)
- Constants: UPPER_SNAKE_CASE

**Code Splitting Metrics:**
- Max function length: 40 lines
- Max file length: 300 lines

**Type Safety:**
- All function signatures typed with Pydantic v2 models
- `from __future__ import annotations` in all files

---

### 5. API & Interface Contracts

**Service Interface:**
```python
# src/services/session_lifecycle.py
class SessionLifecycle:
    async def transition(
        self,
        session_id: UUID,
        to_status: SessionStatus,
        reason: str | None = None,
    ) -> TransitionResult:
        """Attempt a status transition. Returns result with success/failure."""

    async def mark_failed(
        self,
        session_id: UUID,
        error: str,
    ) -> TransitionResult:
        """Mark session as failed and add to retry queue."""

    async def set_notes_ready(
        self,
        session_id: UUID,
        ready: bool = True,
    ) -> None:
        """Set notes_ready flag independently of status."""

    async def get_retry_queue(
        self,
        limit: int = 50,
    ) -> list[RetryJob]:
        """Get failed sessions eligible for retry."""

    async def retry_session(
        self,
        session_id: UUID,
    ) -> TransitionResult:
        """Retry a failed session from the retained transcript (NFR-R4)."""
```

**DB Schema (session status constraint):**
```sql
ALTER TABLE sessions
ADD CONSTRAINT ck_session_status_valid
CHECK (status IN ('created', 'recording', 'transcribed', 'processing', 'complete', 'failed'));
```

**Optimistic Locking Query:**
```sql
UPDATE sessions
SET status = $1, updated_at = now()
WHERE id = $2 AND status = $3 AND updated_at = $4
RETURNING id, status, updated_at;
```
If no rows returned → concurrent modification → retry.

**Event/Message Contracts:**
```json
{
  "event": "session.status_changed",
  "session_id": "uuid",
  "subject_id": "uuid",
  "from_status": "transcribed",
  "to_status": "processing",
  "timestamp": "2026-09-12T10:00:00Z"
}
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Default |
|----------|------|-------------|---------|
| `SESSION_LIFECYCLE_ENABLED` | bool | Enable lifecycle enforcement | `true` |
| `RETRY_MAX_ATTEMPTS` | int | Max retries for failed sessions | `3` |
| `RETRY_BACKOFF_BASE_S` | int | Base backoff in seconds | `60` |
| `RETRY_QUEUE_POLL_INTERVAL_S` | int | How often to check retry queue | `30` |

**Third-Party Integration Contracts:**
- SQLAlchemy: ORM and async queries
- FastAPI: API layer for session status endpoints

**Version Pins:**
- SQLAlchemy >= 2.0.52
- FastAPI >= 0.141.1

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T23.1 | U | `pytest tests/test_session_lifecycle.py::test_illegal_transitions_rejected -v` | Every illegal transition rejected (exhaustive matrix) |
| T23.2 | I | `pytest tests/test_session_lifecycle.py::test_stage_failure_sets_failed -v` | A stage failure sets `failed`, never `complete` |
| T23.3 | I | `pytest tests/test_session_lifecycle.py::test_failed_in_retry_queue -v` | Failed session appears in the retry queue |
| T23.4 | I | `pytest tests/test_session_lifecycle.py::test_reprocess_without_recapture -v` | Reprocessing a failed session from retained transcript succeeds without re-capture |
| T23.5 | I | `pytest tests/test_session_lifecycle.py::test_concurrent_transitions -v` | Concurrent transition attempts resolve to one winner |

**Test Case Details (Given/When/Then):**

**T23.1 — Illegal transitions rejected**
- **Given:** a session in `created` status
- **When:** attempting transition to `transcribed`, `processing`, or `complete`
- **Then:** each raises `ValueError` with descriptive message; session remains in `created`

**T23.2 — Stage failure sets failed, never complete**
- **Given:** a session in `processing` status
- **When:** a pipeline stage raises an exception
- **Then:** session status is set to `failed`, not `complete`; error recorded in `agent_runs`

**T23.3 — Failed session in retry queue**
- **Given:** a session transitions to `failed`
- **When:** the retry queue is queried
- **Then:** the session appears with retry_count=0, error message, and failed_at timestamp

**T23.4 — Reprocessing from retained transcript**
- **Given:** a session in `failed` status with transcript committed
- **When:** `retry_session()` is called
- **Then:** session re-enters `transcribed` → `processing`; transcript is not re-captured (NFR-R4)

**T23.5 — Concurrent transitions resolve to one winner**
- **Given:** a session in `transcribed` status
- **When:** two concurrent `transition(to_status=processing)` calls are made
- **Then:** exactly one succeeds (status becomes `processing`); the other fails with concurrency error

**Verification Commands:**
```bash
uv run pytest tests/test_session_lifecycle.py -v && \
uv run mypy --strict src/services/session_lifecycle.py && \
uv run ruff check src/services/session_lifecycle.py
```

**Exit Criteria:**
- [ ] T23.1 passes — all illegal transitions rejected
- [ ] T23.2 passes — stage failure sets `failed`, never `complete`
- [ ] T23.3 passes — failed session in retry queue
- [ ] T23.4 passes — reprocessing without re-capture works
- [ ] T23.5 passes — concurrent transitions resolve correctly

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- Without optimistic locking, concurrent transitions can create split state (one worker says `processing`, another says `failed`)
- `notes_ready` must be separate from status — a session can be `complete` but notes not yet ready (during synthesis)
- Retry queue must use exponential backoff — immediate retry on transient failure wastes resources
- `failed` sessions with no transcript committed cannot be retried — must re-capture audio

**Fallback Instructions:**
- If lifecycle service is down: pipeline stages should fail fast, not silently skip transitions
- If retry queue grows > 100: alert operator, investigate root cause
- If `updated_at` not available for locking: fall back to `SELECT ... FOR UPDATE`

**Rollback Procedure:**
- Revert code changes only — no database migration rollback needed (status CHECK constraint is idempotent)
- Retry queue is transient (in-memory or separate table); clearing it is safe
- Feature flag: `SESSION_LIFECYCLE_ENABLED=false` disables transition guards (emergency only)

---

### 9. Observability (if applicable)

**Metrics Added:**
- `session_transition_total`: counter of transitions (labels: from_status, to_status, success=true/false)
- `session_status_current`: gauge of sessions per status (labels: status)
- `session_retry_queue_size`: gauge of pending retries
- `session_retry_total`: counter of retry attempts (labels: success=true/false)
- `session_failed_total`: counter of failures (labels: stage)

**Tracing/Logging:**
- Span: `session.lifecycle.transition` with attributes (session_id, from_status, to_status, success)
- Log: WARN on illegal transition attempt
- Log: INFO on each successful transition
- Log: ERROR on failure with full error context

**Alerts:**
- Retry queue size > 50: pipeline backlog
- Failure rate > 10% in 1 hour: systemic issue
- Transition to `failed` from `processing`: investigate pipeline stage

---

### 10. Exit Checklist

- [ ] All tests pass (T23.1, T23.2, T23.3, T23.4, T23.5)
- [ ] Single `SessionLifecycle` service enforces all transitions
- [ ] DB CHECK constraint validates status enum
- [ ] Retry queue operational with exponential backoff
- [ ] `notes_ready` flag managed independently of status
- [ ] No session can be silently half-processed
- [ ] Every failure is visible and recoverable
