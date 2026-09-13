# S39 — Observability: Tracing & Cost Attribution
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Deploy LangFuse with OpenTelemetry tracing so every LLM call is traceable, costed, and queryable via `agent_runs`, with agent isolation machine-verifiable.

**Component Boundaries:**
- **Allowed:** `src/services/observability/`, `config/langfuse.yaml`, Docker Compose additions for LangFuse, `tests/test_observability.py`
- **Off-limits:** Schema registry (S38), prompt versioning (S40), agent implementations (S56–S57)

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| LangFuse | 2.x | LLM observability platform |
| OpenTelemetry | 1.x | Distributed tracing |
| LangFuse Python SDK | 2.x | Trace instrumentation |
| PostgreSQL | 16.x | LangFuse backend storage |
| pytest | 8.x | Integration tests |

---

### 2. State Machine & Domain Schemas

**Trace Lifecycle:**
```
trace_start → node_invoke → node_complete → ... → session_complete
     ↓              ↓              ↓                     ↓
  agent_runs   agent_runs    agent_runs            agent_runs
   (start)      (running)     (running)            (complete/failed)
```

**Pydantic Models:**
```python
# src/services/observability/models.py
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum


class AgentRunStatus(str, Enum):
    STARTED = "started"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


class AgentRun(BaseModel):
    id: str
    session_id: str
    trace_id: str
    agent_id: str
    model: str
    tier: str
    prompt_version: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = Field(default=0.0, ge=0.0)
    latency_ms: int = Field(default=0, ge=0)
    status: AgentRunStatus
    started_at: datetime
    completed_at: datetime | None = None
    error: str | None = None


class TraceContext(BaseModel):
    trace_id: str
    session_id: str
    parent_span_id: str | None = None
```

**agent_runs Table Schema:**
```sql
CREATE TABLE agent_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL,
    trace_id VARCHAR(64) NOT NULL,
    agent_id VARCHAR(10) NOT NULL,
    model VARCHAR(100) NOT NULL,
    tier VARCHAR(20) NOT NULL,
    prompt_version VARCHAR(50) NOT NULL,
    input_tokens INT DEFAULT 0,
    output_tokens INT DEFAULT 0,
    total_tokens INT DEFAULT 0,
    cost_usd DECIMAL(10, 6) DEFAULT 0.0,
    latency_ms INT DEFAULT 0,
    status VARCHAR(20) NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    error TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_agent_runs_session ON agent_runs(session_id);
CREATE INDEX idx_agent_runs_trace ON agent_runs(trace_id);
CREATE INDEX idx_agent_runs_agent ON agent_runs(agent_id);
CREATE INDEX idx_agent_runs_tier ON agent_runs(tier);
```

**State Transition Rules:**
- Trace starts when Prefect flow begins
- Each LangGraph node invocation creates a span
- `agent_runs` row created at span start, updated at completion
- `trace_id` propagated from Prefect flow context through all nodes

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Add LangFuse service to Docker Compose with PostgreSQL | Service starts, health check passes |
| 2 | Create `agent_runs` table with indexes | Table exists, indexes created |
| 3 | Implement `TraceManager` with `trace_id` propagation | Unit test: trace_id consistent across spans |
| 4 | Instrument Prefect tasks with OpenTelemetry spans | Traces appear in LangFuse UI |
| 5 | Instrument LangGraph nodes with OpenTelemetry spans | Node-level tracing visible |
| 6 | Wire `agent_runs` writes on every LLM invocation | Integration test: row created per call |
| 7 | Implement cost computation from token counts | SQL query returns per-session cost |
| 8 | Implement agent isolation assertion (no A3→A5 or A5→A3) | T39.5: assertion passes |
| 9 | Verify trace content excludes raw transcripts | T39.4: NFR-S10 compliance |

**Atomic Sub-tasks:**
1. LangFuse Docker Compose service with PostgreSQL
2. `agent_runs` table DDL and migration
3. `TraceManager` with context propagation
4. Prefect task instrumentation
5. LangGraph node instrumentation
6. Cost computation query
7. Agent isolation assertion
8. Transcript redaction for NFR-S10

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| LangFuse unavailable | Traces buffered locally, flushed on reconnect |
| `trace_id` propagation fails | Use fallback UUID, log warning |
| Cost computation overflow | Use DECIMAL(10,6), cap at reasonable max |
| Agent isolation violated (A3→A5 edge) | Alert immediately, block deployment |
| `agent_runs` write fails | Log error, don't block LLM call |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Context propagation pattern: `trace_id` flows through contextvars
- Write-ahead pattern: `agent_runs` row created before LLM call
- Observer pattern: spans emitted on each node transition

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase
- Files: snake_case (`trace_manager.py`, `cost_attribution.py`)
- SQL: snake_case, lowercase keywords

**Code Splitting Metrics:**
- Max function length: 40 lines
- Max file length: 300 lines

**Type Safety:**
- All function signatures typed
- `from __future__ import annotations` in all files
- Pydantic models for all data structures

---

### 5. API & Interface Contracts

**TraceManager Interface:**
```python
# src/services/observability/trace_manager.py
from contextvars import ContextVar

trace_id_var: ContextVar[str] = ContextVar("trace_id")
session_id_var: ContextVar[str] = ContextVar("session_id")


class TraceManager:
    def start_trace(self, session_id: str) -> str:
        """Start a new trace, return trace_id."""
        ...

    def start_span(self, name: str, attributes: dict) -> str:
        """Start a span within the current trace."""
        ...

    def end_span(self, span_id: str, attributes: dict | None = None):
        """End a span with optional attributes."""
        ...

    def record_agent_run(self, run: AgentRun):
        """Write an agent_runs row."""
        ...
```

**Cost Attribution Query:**
```sql
-- Per-session cost
SELECT
    session_id,
    SUM(cost_usd) AS total_cost_usd,
    SUM(input_tokens) AS total_input_tokens,
    SUM(output_tokens) AS total_output_tokens,
    COUNT(*) AS total_agent_calls,
    AVG(latency_ms) AS avg_latency_ms
FROM agent_runs
WHERE session_id = :session_id
GROUP BY session_id;

-- Per-tier cost breakdown
SELECT
    tier,
    SUM(cost_usd) AS cost_usd,
    COUNT(*) AS call_count
FROM agent_runs
WHERE session_id = :session_id
GROUP BY tier;

-- Per-agent cost breakdown
SELECT
    agent_id,
    model,
    tier,
    SUM(cost_usd) AS cost_usd,
    SUM(total_tokens) AS total_tokens,
    AVG(latency_ms) AS avg_latency_ms
FROM agent_runs
WHERE session_id = :session_id
GROUP BY agent_id, model, tier;
```

**Agent Isolation Assertion:**
```sql
-- No A3→A5 or A5→A3 edges in trace graph
SELECT COUNT(*) AS violation_count
FROM agent_runs r1
JOIN agent_runs r2
    ON r1.trace_id = r2.trace_id
    AND r1.session_id = r2.session_id
    AND r1.completed_at <= r2.started_at
WHERE (r1.agent_id = 'A3' AND r2.agent_id = 'A5')
   OR (r1.agent_id = 'A5' AND r2.agent_id = 'A3');
-- Must return 0
```

**Docker Compose Addition:**
```yaml
services:
  langfuse:
    image: langfuse/langfuse:2
    ports:
      - "3000:3000"
    environment:
      DATABASE_URL: postgresql://langfuse:langfuse@langfuse-db:5432/langfuse
      NEXTAUTH_SECRET: ${LANGFuse_NEXTAUTH_SECRET}
      SALT: ${LANGFuse_SALT}
    depends_on:
      langfuse-db:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3000/api/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  langfuse-db:
    image: postgres:16
    environment:
      POSTGRES_DB: langfuse
      POSTGRES_USER: langfuse
      POSTGRES_PASSWORD: ${LANGFuse_DB_PASSWORD}
    volumes:
      - langfuse_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U langfuse"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  langfuse_data:
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Default |
|----------|------|-------------|---------|
| `LANGFUSE_HOST` | string | LangFuse URL | `http://langfuse:3000` |
| `LANGFUSE_PUBLIC_KEY` | string | LangFuse public key | — |
| `LANGFUSE_SECRET_KEY` | string | LangFuse secret key | — |
| `LANGFUSE_DB_PASSWORD` | string | PostgreSQL password | — |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | string | OpenTelemetry collector URL | `http://otel:4317` |
| `TRACE_SAMPLE_RATE` | float | Sampling rate for traces | `1.0` |

**Third-Party Integration Contracts:**
- LangFuse: REST API for trace ingestion and querying
- OpenTelemetry: OTLP export to collector

**Version Pins:**
- LangFuse image pinned in Docker Compose
- LangFuse Python SDK pinned in `pyproject.toml`
- OpenTelemetry packages pinned in `pyproject.toml`

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T39.1 | I | `pytest tests/test_observability.py::test_agent_call_produces_trace -v` | Every agent call produces a LangFuse trace and `agent_runs` row |
| T39.2 | I | `pytest tests/test_observability.py::test_trace_id_correlation -v` | `trace_id` correlates full session spans end-to-end |
| T39.3 | I | `pytest tests/test_observability.py::test_per_session_cost -v` | Per-session cost computable by SQL from `agent_runs` |
| T39.4 | S | `pytest tests/test_observability.py::test_traces_exclude_transcripts -v` | Traces exclude raw transcript content |
| T39.5 | I | `pytest tests/test_observability.py::test_agent_isolation -v` | No A3→A5 or A5→A3 edge in trace graph |

**Test Case Details (Given/When/Then):**

**T39.1 — Every agent call produces trace and agent_runs row**
- **Given:** a session with 3 agent invocations (A1, A3, A1)
- **When:** the session completes
- **Then:** 3 LangFuse traces exist and 3 `agent_runs` rows are present with correct agent_id

**T39.2 — trace_id correlates full session**
- **Given:** a session with trace_id `abc-123` spanning A1→A3→A1
- **When:** querying `agent_runs` for `trace_id = 'abc-123'`
- **Then:** all 3 rows share the same `trace_id`, spans are ordered by time

**T39.3 — Per-session cost computable by SQL**
- **Given:** `agent_runs` rows with token counts and tier costs
- **When:** the cost attribution SQL is executed
- **Then:** total cost matches manual calculation (tokens × tier price)

**T39.4 — Traces exclude raw transcripts (NFR-S10)**
- **Given:** a session with student conversation content
- **When:** the LangFuse trace is inspected
- **Then:** no raw student messages appear in the trace; only metadata (token counts, latency, tier) is present

**T39.5 — Agent isolation assertion**
- **Given:** a set of `agent_runs` for multiple sessions
- **When:** the isolation SQL query is executed
- **Then:** violation_count is 0 (no A3→A5 or A5→A3 edges)

**Verification Commands:**
```bash
docker compose up -d langfuse langfuse-db && \
sleep 30 && \
uv run pytest tests/test_observability.py -v -k "S39 or observability or tracing" && \
uv run mypy --strict src/services/observability/ && \
uv run ruff check src/services/observability/
```

**Exit Criteria:**
- [ ] T39.1 passes — every agent call produces trace and `agent_runs` row
- [ ] T39.2 passes — `trace_id` correlates full session
- [ ] T39.3 passes — per-session cost computable by SQL
- [ ] T39.4 passes — traces exclude raw transcripts (NFR-S10)
- [ ] T39.5 passes — no A3→A5 or A5→A3 edges (AC-15 precursor)

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- LangFuse ingestion can lag under high load — buffer traces locally if LangFuse is unreachable
- `trace_id` must be propagated via contextvars, not global state — concurrent sessions would corrupt
- Cost computation assumes fixed per-token pricing — update rates when provider pricing changes
- Agent isolation assertion is a query, not a runtime guard — run in CI and as a periodic check

**Fallback Instructions:**
- If LangFuse is down: buffer traces in memory, flush on reconnect; `agent_runs` writes to local DB
- If OpenTelemetry export fails: traces are lost but `agent_runs` rows are still written
- If cost computation returns NaN: check for division by zero (no tokens used)

**Rollback Procedure:**
- Stop LangFuse: `docker compose stop langfuse langfuse-db`
- Remove OpenTelemetry instrumentation from agents
- `agent_runs` table remains (historical data preserved)
- No data loss on rollback

---

### 9. Observability (if applicable)

**Metrics Added:**
- `agent_runs_total`: counter (labels: agent_id, tier, status)
- `agent_runs_cost_usd`: histogram of per-call costs
- `agent_runs_latency_seconds`: histogram of per-call latency
- `trace_buffer_size`: gauge of locally buffered traces
- `langfuse_ingestion_latency_seconds`: histogram of trace ingestion time

**Tracing/Logging:**
- Span: `agent_run.complete` with attributes (agent_id, model, tier, tokens, cost, latency_ms)
- Log: WARNING when LangFuse unavailable, traces buffered
- Log: ERROR on agent isolation violation

**Alerts:**
- Agent isolation violation detected: immediate alert, block deployment
- LangFuse ingestion latency > 30s: investigate LangFuse health
- `agent_runs` write failure rate > 1%: check database connectivity

---

### 10. Exit Checklist

- [ ] All tests pass (T39.1, T39.2, T39.3, T39.4, T39.5)
- [ ] LangFuse deployed and accessible
- [ ] `agent_runs` table created with indexes
- [ ] Every LLM call produces a trace and `agent_runs` row
- [ ] `trace_id` propagates end-to-end through all spans
- [ ] Per-session cost computable by SQL (NFR-C1)
- [ ] Traces exclude raw transcripts (NFR-S10)
- [ ] Agent isolation (no A3→A5 or A5→A3) verified by automated assertion
