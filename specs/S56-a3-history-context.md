# S56 — A3 History Context
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Implement A3 agent that identifies relationships between current session content and prior stored content by querying DB-1/DB-2 through RetrievalService (read-only), emitting typed links (`builds_on`, `revisits`, `contradicts`, `prerequisite_for`) surfaced as cross-references in notes.

**Component Boundaries:**
- **Allowed:** `src/agents/a3/`, `src/services/retrieval/` (client only), `src/db/repositories/`, `tests/test_a3_history.py`, `config/prompts/a3.yaml`
- **Off-limits:** RetrievalService implementation (S55), A5 agent (S57), note generation (S38)

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| LangGraph | 0.2.x | Agent orchestration |
| LangFuse | 0.40.x | Prompt versioning + tracing |
| Pydantic | 2.13.5 | Output schemas |
| pytest | 8.x | Integration tests |
| testcontainers | 4.6.x | PostgreSQL for integration tests |

---

### 2. State Machine & Domain Schemas

**A3 Link Types:**
```
builds_on    — current session extends a prior topic
revisits     — current session re-examines a prior topic
contradicts  — current session conflicts with prior content
prerequisite_for — current session is a prerequisite for a prior topic
```

**A3 Output Schema:**
```python
# src/agents/a3/models.py
from pydantic import BaseModel, Field
from uuid import UUID
from enum import Enum

class LinkType(str, Enum):
    BUILDS_ON = "builds_on"
    REVISITS = "revisits"
    CONTRADICTS = "contradicts"
    PREREQUISITE_FOR = "prerequisite_for"

class CrossSessionLink(BaseModel):
    link_type: LinkType
    source_session_id: UUID
    target_session_id: UUID
    source_topic_name: str
    target_topic_name: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    evidence: str = Field(..., max_length=500)

class A3Output(BaseModel):
    links: list[CrossSessionLink] = Field(default_factory=list)
    summary: str = Field(..., max_length=2000)
    relationships_found: int = Field(..., ge=0)
    confidence_threshold: float = Field(default=0.6, ge=0.0, le=1.0)

class A3Input(BaseModel):
    session_id: UUID
    subject_id: UUID
    current_session_content: str  # transcript or notes summary
    current_topic_names: list[str]
    prior_session_ids: list[UUID]  # for scoping retrieval
```

**A3 Prompt Version:**
```yaml
# config/prompts/a3.yaml
version: "1.0.0"
system: |
  You are A3, a cross-session relationship analyst. Your task is to identify
  meaningful connections between the current lecture session and prior sessions
  in the same subject.
  
  You MUST:
  1. Use only the provided retrieval results — do not hallucinate connections
  2. Assign exactly one LinkType to each relationship:
     - builds_on: current extends a prior topic
     - revisits: current re-examines a prior topic
     - contradicts: current conflicts with prior content
     - prerequisite_for: current is needed before a prior topic
  3. Provide evidence from the retrieval results
  4. Set confidence based on strength of evidence (0.0-1.0)
  5. Skip relationships with confidence < 0.6
  
  You MUST NOT:
  - Access any database directly
  - Call any other agent
  - Generate notes or questions
  - Fabricate connections not supported by retrieval results
```

**State Transition Rules:**
- A3 receives session content + retrieval results → outputs typed links
- Links below confidence threshold (0.6) are discarded
- Empty output is valid for first session (no prior history)

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Create `src/agents/a3/models.py` with Pydantic schemas | Import succeeds, mypy passes |
| 2 | Create `src/agents/a3/prompt.py` with LangFuse prompt loading | Prompt loads correctly |
| 3 | Implement `A3Agent` class with LangGraph node | Agent instantiation succeeds |
| 4 | Implement relationship identification logic | Unit test: identifies link on prepared fixture |
| 5 | Add read-only DB access enforcement | T56.2: write attempt rejected |
| 6 | Add A5 isolation enforcement | T56.3: no A5 calls in traces |
| 7 | Add empty history handling | T56.5: first session returns empty, no error |
| 8 | Write integration tests with multi-session fixture | T56.1, T56.4 pass |

**Atomic Sub-tasks:**
1. A3 output schemas (CrossSessionLink, A3Output)
2. A3 prompt versioning with LangFuse
3. A3 agent implementation with LangGraph
4. Read-only DB access enforcement
5. A5 isolation assertion in traces
6. Multi-session test fixture
7. Human review evaluation (40 links)

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| No prior sessions exist | Return empty links, summary: "No prior history found" |
| Retrieval returns no results | Return empty links, summary: "No related content found" |
| All links below confidence threshold | Return empty links, summary: "Potential connections weak" |
| A3 attempts DB write | DB role denies; agent_run logged as failed |
| A3 attempts A5 call | Trace assertion fails; not in agent interface |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Agent pattern: A3 as LangGraph node with structured output
- Repository pattern: read-only repository for session/topic queries
- Prompt versioning: LangFuse for prompt management and A/B testing
- Isolation: A3 has no interface to A5 — structurally impossible

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase (`A3Agent`, `CrossSessionLink`)
- Files: snake_case (`a3_agent.py`, `cross_session_link.py`)
- Functions: snake_case (`identify_relationships`, `filter_by_confidence`)
- Constants: UPPER_SNAKE_CASE

**Code Splitting Metrics:**
- Max function length: 40 lines
- Max file length: 300 lines
- Max class methods: 8

**Type Safety:**
- All function signatures typed with Pydantic v2 models
- `from __future__ import annotations` in all files
- UUID type hints for all ID parameters
- LinkType enum enforced at schema level

---

### 5. API & Interface Contracts

**Internal API:**
```python
# src/agents/a3/agent.py
class A3Agent:
    def __init__(
        self,
        retrieval_service: RetrievalService,
        db_session: AsyncSession,  # read-only
        prompt_version: str = "1.0.0",
    ):
        ...

    async def run(self, input: A3Input) -> A3Output:
        """Identify cross-session relationships. Read-only, no A5 calls."""
        ...

    async def _retrieve_related_content(
        self, query: str, subject_id: UUID, session_ids: list[UUID]
    ) -> list[RetrievalResult]:
        """Retrieve related content from prior sessions."""
        ...

    def _filter_by_confidence(
        self, links: list[CrossSessionLink], threshold: float = 0.6
    ) -> list[CrossSessionLink]:
        """Filter links below confidence threshold."""
        ...
```

**Cross-Reference Schema (for notes):**
```python
# src/agents/a3/cross_reference.py
class NoteCrossReference(BaseModel):
    """Cross-reference to include in generated notes."""
    link_type: LinkType
    related_topic_name: str
    related_session_id: UUID
    evidence_snippet: str = Field(..., max_length=200)
    confidence: float

class NoteCrossReferences(BaseModel):
    """Collection of cross-references for a note."""
    references: list[NoteCrossReference] = Field(default_factory=list)
    summary: str = Field(..., max_length=500)
```

**Mock Request/Response Payloads:**
```json
// A3Input
{
  "session_id": "660e8400-e29b-41d4-a716-446655440001",
  "subject_id": "550e8400-e29b-41d4-a716-446655440000",
  "current_session_content": "Today we covered advanced gradient descent variants...",
  "current_topic_names": ["Advanced Optimization", "Learning Rate Schedules"],
  "prior_session_ids": ["770e8400-e29b-41d4-a716-446655440002"]
}

// A3Output
{
  "links": [
    {
      "link_type": "builds_on",
      "source_session_id": "660e8400-e29b-41d4-a716-446655440001",
      "target_session_id": "770e8400-e29b-41d4-a716-446655440002",
      "source_topic_name": "Advanced Optimization",
      "target_topic_name": "Gradient Descent Basics",
      "confidence": 0.85,
      "evidence": "Session covers momentum and Adam, building on basic gradient descent from prior session"
    }
  ],
  "summary": "Current session builds directly on gradient descent basics covered in the previous session.",
  "relationships_found": 1,
  "confidence_threshold": 0.6
}
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Default |
|----------|------|-------------|---------|
| `DATABASE_URL` | string | PG-MAIN connection (asyncpg, READ-ONLY) | `postgresql+asyncpg://localhost:5432/lis` |
| `SYLLABUS_DATABASE_URL` | string | PG-SYLLABUS connection | `postgresql+asyncpg://localhost:5432/lis_syllabus` |
| `RERANKER_ENDPOINT` | string | Reranker service URL | `http://reranker:80` |
| `LANGFUSE_PUBLIC_KEY` | string | LangFuse public key | — |
| `LANGFUSE_SECRET_KEY` | string | LangFuse secret key | — |
| `A3_PROMPT_VERSION` | string | A3 prompt version | `1.0.0` |
| `A3_CONFIDENCE_THRESHOLD` | float | Minimum confidence for links | `0.6` |

**Third-Party Integration Contracts:**
- RetrievalService (S55): stateless retrieval with hybrid recall + rerank
- LangFuse: prompt versioning, tracing, agent_runs audit
- LangGraph: agent orchestration, structured output

**Version Pins:**
- `langgraph` pinned in `pyproject.toml`
- `langfuse` pinned in `pyproject.toml`
- A3 prompt version pinned in `config/prompts/a3.yaml`

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T56.1 | I | `pytest tests/test_a3_history.py::test_identifies_relationship -v` | A3 identifies a genuine relationship on a prepared multi-session fixture |
| T56.2 | S | `pytest tests/test_a3_history.py::test_readonly_db_access -v` | Write attempt rejected at the database level |
| T56.3 | I | `pytest tests/test_a3_history.py::test_no_a5_communication -v` | No A3↔A5 communication in traces |
| T56.4 | V | `pytest tests/test_a3_history.py::test_link_quality -v` | Human review: links judged meaningful ≥ 0.75 on 40 links |
| T56.5 | I | `pytest tests/test_a3_history.py::test_first_session_empty -v` | A3 on first session returns empty, no error |

**Test Case Details (Given/When/Then):**

**T56.1 — Identifies relationship on multi-session fixture**
- **Given:** 3 prior sessions covering "Gradient Descent", "Neural Networks", "Backpropagation" and a current session on "Advanced Optimization"
- **When:** A3Agent.run() is called with the current session content
- **Then:** output contains at least one `builds_on` link connecting "Advanced Optimization" to "Gradient Descent" with confidence > 0.6

**T56.2 — Read-only DB access**
- **Given:** A3Agent is instantiated with a DB connection configured as read-only
- **When:** agent attempts to write (INSERT/UPDATE/DELETE) — simulated by the test
- **Then:** database rejects the write with a permission error

**T56.3 — No A5 communication**
- **Given:** A3Agent is run with tracing enabled
- **When:** execution trace is inspected
- **Then:** no calls to A5 appear in the trace; no shared state with A5

**T56.4 — Link quality (human review)**
- **Given:** 40 links generated by A3 on a diverse set of sessions
- **When:** human reviewers score each link for meaningfulness (0-1)
- **Then:** mean score ≥ 0.75

**T56.5 — First session returns empty**
- **Given:** a subject with only one session (no prior history)
- **When:** A3Agent.run() is called
- **Then:** output contains 0 links, summary indicates no prior history, no error raised

**Verification Commands:**
```bash
# Full local verification
uv run pytest tests/test_a3_history.py -v -k "S56 or a3_history" && \
uv run mypy --strict src/agents/a3/ && \
uv run ruff check src/agents/a3/
```

**Exit Criteria:**
- [ ] T56.1 passes — identifies genuine relationships
- [ ] T56.2 passes — read-only DB access enforced
- [ ] T56.3 passes — no A5 communication in traces
- [ ] T56.4 passes — link quality ≥ 0.75 on human review
- [ ] T56.5 passes — first session returns empty, no error

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- A3 must not hallucinate connections — enforce with retrieval evidence
- Read-only DB role must be enforced at the database level, not just application level
- A5 isolation is structural — A3 must have no interface to A5, not just no calls
- Confidence threshold tuning affects link quality — 0.6 is a starting point

**Fallback Instructions:**
- If A3 generates no links on a session with obvious connections: lower confidence threshold or check retrieval quality
- If A3 attempts DB write: verify DB role is read-only at the database level
- If A3 connects to A5: check trace logs, verify no shared state

**Rollback Procedure:**
- Disable A3 in pipeline: remove A3 node from LangGraph workflow
- No database migrations required
- A3 output is additive to notes — removing it does not break note generation
- Feature flag: `A3_ENABLED=false` in `.env`

---

### 9. Observability (if applicable)

**Metrics Added:**
- `a3_links_total`: counter of links generated (labels: link_type)
- `a3_confidence_histogram`: histogram of link confidence scores
- `a3_latency_seconds`: histogram of A3 execution latency
- `a3_empty_sessions_total`: counter of sessions with no links found

**Tracing/Logging:**
- Span: `a3.run` with child spans for retrieval, link generation
- Log: INFO on links generated with types and confidence scores
- Log: DEBUG on retrieval results used for link generation
- Log: WARNING on low-confidence links being filtered

**Alerts:**
- A3 generates 0 links for 10+ consecutive sessions: investigate retrieval quality
- A3 latency > 30s: check retrieval performance or prompt complexity

---

### 10. Exit Checklist

- [ ] All tests pass (T56.1–T56.5)
- [ ] A3 identifies meaningful cross-session relationships
- [ ] Read-only DB access enforced at database level
- [ ] No A3↔A5 communication in traces
- [ ] Link quality ≥ 0.75 on human review
- [ ] First session returns empty links without error
- [ ] Cross-references surfaced in generated notes
