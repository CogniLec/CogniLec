# S41 — A1 Relevance Filter
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** A1 classifies utterances (batched) as on/off-topic against the identified topic, producing `is_relevant` + `filter_reason` decisions written as soft-delete markers — never row removal.

**Component Boundaries:**
- **Allowed:** `src/services/agents/a1/`, `config/prompts/a1_relevance/`, `src/db/repositories/utterance_repository.py`, `tests/test_a1_relevance.py`
- **Off-limits:** A1 evaluation (S42), ensemble voting (S43), note synthesis (S44), prompt versioning (S40)

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| Local LLM | Tier 1 (S36) | Primary inference for relevance classification |
| Pydantic | 2.x | Schema definitions for A1 output |
| SQLAlchemy | 2.0.52 | DB writes for utterance filter decisions |
| pytest | 8.x | Integration tests |

---

### 2. State Machine & Domain Schemas

**A1 Classification Flow:**
```
utterances_batch_in → A1_LLM_call → relevance_decision
                                     ├─ is_relevant=true  (KEEP)
                                     └─ is_relevant=false (DISCARD, with filter_reason)
                     → write to DB-1 (is_relevant, filter_reason)
```

**Filter Symmetry (FR-2.14):**
```
speaker_tag=lecturer  → same A1 prompt, same threshold
speaker_tag=student   → same A1 prompt, same threshold
```
Filtering is topic-based, not speaker-based. A student question on-topic is retained; a lecturer aside off-topic is discarded.

**A1 Classification Output Schema:**
```python
# src/services/agents/a1/models.py
from pydantic import BaseModel, Field
from enum import Enum


class RelevanceDecision(str, Enum):
    KEEP = "keep"
    DISCARD = "discard"


class A1UtteranceResult(BaseModel):
    utterance_id: str
    is_relevant: bool
    decision: RelevanceDecision
    filter_reason: str = Field(..., min_length=1, max_length=200)
    confidence: float = Field(..., ge=0.0, le=1.0)
    topic_alignment: str = Field(..., description="How utterance relates to identified topic")


class A1BatchResult(BaseModel):
    session_id: str
    topic_id: str | None = None
    topic_description: str = Field(..., min_length=1)
    results: list[A1UtteranceResult] = Field(..., min_length=1)
    model: str
    prompt_version: str
```

**State Transition Rules:**
- Utterance starts with `is_relevant=NULL` (unfiltered default)
- A1 writes `is_relevant=true|false` + `filter_reason` — this is a soft delete, never row removal (FR-2.15)
- `outlier_score` from HDBSCAN is passed as a prompt feature, not a gate (v2.0 §3.3)
- A1 treats lecturer and student utterances identically (FR-2.14)

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Define A1 output Pydantic schema in `src/services/agents/a1/models.py` | Schema imports, validates sample output |
| 2 | Create A1 prompt template in `config/prompts/a1_relevance/v1.md` with topic context, utterance batch, outlier score feature | Prompt loads from versioned registry |
| 3 | Implement `A1FilterAgent` class with `classify_batch()` method | Unit test: mock LLM returns valid batch result |
| 4 | Implement batch construction logic: group utterances by session, inject topic context and outlier scores | Unit test: batch boundaries are session-scoped |
| 5 | Implement soft-delete writes: update `is_relevant` and `filter_reason` on `utterances` table | Integration test: DB writes are correct |
| 6 | Verify symmetry: lecturer and student utterances processed identically | T41.2, T41.3 pass |
| 7 | Verify rationale is machine-readable for threshold tuning | T41.5 passes |
| 8 | Run full integration test suite | T41.1–T41.6 pass |

**Atomic Sub-tasks:**
1. A1 output Pydantic schema definition
2. Versioned prompt template with topic context and outlier score feature
3. Batch construction logic (session-scoped utterance grouping)
4. `A1FilterAgent.classify_batch()` implementation
5. Soft-delete write logic (update `is_relevant`, `filter_reason`)
6. Machine-readable rationale format validation

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| Empty utterance batch | Skip processing, log warning |
| Topic not identified (NULL topic_id) | Process with generic topic context; flag for review |
| LLM returns partial results | Retry batch; if still partial, process available results |
| LLM timeout | Retry once with exponential backoff; if still timeout, mark batch as unprocessed |
| Outlier score missing | Omit from prompt; proceed without |
| Batch size exceeds model context | Split into sub-batches, merge results |
| Filter reason exceeds 200 chars | Truncate with `...` suffix |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Agent pattern: `A1FilterAgent` encapsulates classification logic
- Repository pattern: `UtteranceRepository.update_filter_decision()` for DB writes
- Strategy pattern: prompt versioned via registry (S40)
- Batching pattern: utterances grouped by session for LLM efficiency

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase (`A1FilterAgent`, `A1UtteranceResult`)
- Files: snake_case (`a1_filter.py`, `models.py`)
- Functions: snake_case (`classify_batch`, `update_filter_decision`)
- Constants: UPPER_SNAKE_CASE (`FILTER_REASON_MAX_LENGTH`)

**Code Splitting Metrics:**
- Max function length: 40 lines
- Max file length: 300 lines
- Max class methods: 8

**Type Safety:**
- All function signatures typed with Pydantic v2 models
- `from __future__ import annotations` in all files
- Return types explicit on all public methods
- DB repository methods return `None` or typed results

---

### 5. API & Interface Contracts

**Internal Agent Interface:**
```python
# src/services/agents/a1/filter.py
class A1FilterAgent:
    def __init__(self, llm_client, prompt_registry, utterance_repo): ...

    async def classify_batch(
        self,
        session_id: UUID,
        utterances: list[Utterance],
        topic_id: UUID | None,
        topic_description: str,
        subject_id: UUID,
    ) -> A1BatchResult:
        """Classify a batch of utterances as on/off-topic.

        Writes is_relevant + filter_reason to DB-1.
        Never removes rows — soft delete only.
        """
        ...

    async def _build_prompt(
        self,
        utterances: list[Utterance],
        topic_description: str,
    ) -> str:
        """Build prompt with utterance text, speaker tags, outlier scores."""
        ...
```

**Repository Interface:**
```python
# src/db/repositories/utterance_repository.py
class UtteranceRepository:
    async def update_filter_decision(
        self,
        subject_id: UUID,
        utterance_id: UUID,
        is_relevant: bool,
        filter_reason: str,
    ) -> None:
        """Write relevance decision to DB-1. Soft delete only."""
        ...

    async def update_batch_decisions(
        self,
        subject_id: UUID,
        decisions: list[A1UtteranceResult],
    ) -> int:
        """Batch update filter decisions. Returns count updated."""
        ...
```

**Prompt Template (`config/prompts/a1_relevance/v1.md`):**
```markdown
# A1 Relevance Filter

You are a lecture transcript relevance classifier.

## Topic Under Discussion
{{topic_description}}

## Outlier Information
HDBSCAN outlier scores indicate how much each utterance deviates from the session's
core content cluster. Higher scores suggest potential tangents, but are not decisive.

## Utterances to Classify
{{#each utterances}}
- ID: {{id}} | Speaker: {{speaker_tag}} | Outlier: {{outlier_score}}
  Text: {{text}}
{{/each}}

## Task
For each utterance, classify as KEEP (on-topic) or DISCARD (off-topic).

## Rules
1. Filtering is topic-based — speaker identity is irrelevant
2. Student questions on-topic must be RETAINED
3. Lecturer asides off-topic should be DISCARDED
4. When uncertain, prefer KEEP (asymmetric cost)
5. Provide a concise, machine-readable reason for each decision

## Output Format (JSON)
{
  "results": [
    {
      "utterance_id": "...",
      "is_relevant": true|false,
      "decision": "keep"|"discard",
      "filter_reason": "...",
      "confidence": 0.0-1.0,
      "topic_alignment": "..."
    }
  ]
}
```

**Database Schema (writes to existing DB-1):**
```sql
-- A1 writes to existing utterances table columns:
UPDATE utterances
SET is_relevant = $1,
    filter_reason = $2
WHERE subject_id = $3 AND id = $4;
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Default |
|----------|------|-------------|---------|
| `A1_MODEL` | string | Model for A1 classification | `tier_1` |
| `A1_TEMPERATURE` | float | LLM temperature for A1 | `0.1` |
| `A1_MAX_BATCH_SIZE` | int | Max utterances per LLM call | `50` |
| `A1_PROMPT_VERSION` | string | Active prompt version | `v1` |
| `A1_FILTER_REASON_MAX` | int | Max chars for filter_reason | `200` |

**Third-Party Integration Contracts:**
- Local LLM (S36): OpenAI-compatible `/v1/chat/completions` endpoint
- Prompt Registry (S40): prompt loading by version reference

**Version Pins:**
- LLM model pinned in `config/models.yaml`
- Prompt version pinned in `config/prompts/a1_relevance/`

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T41.1 | I | `pytest tests/test_a1_relevance.py::test_every_utterance_receives_decision -v` | Every utterance in batch receives `is_relevant` + `filter_reason` |
| T41.2 | I | `pytest tests/test_a1_relevance.py::test_student_question_retained -v` | On-topic student question has `is_relevant=true` |
| T41.3 | I | `pytest tests/test_a1_relevance.py::test_lecturer_aside_discarded -v` | Off-topic lecturer aside has `is_relevant=false` |
| T41.4 | I | `pytest tests/test_a1_relevance.py::test_discarded_not_deleted -v` | Discarded utterances remain in DB-1 with `is_relevant=false` |
| T41.5 | I | `pytest tests/test_a1_relevance.py::test_rationale_machine_readable -v` | `filter_reason` is structured and parseable |
| T41.6 | U | `pytest tests/test_a1_relevance.py::test_batch_boundaries_no_effect -v` | Splitting utterances across batches does not change individual decisions |

**Test Case Details (Given/When/Then):**

**T41.1 — Every utterance receives a decision and rationale**
- **Given:** a session with 30 utterances, a topic "Linear Algebra", and HDBSCAN outlier scores
- **When:** `A1FilterAgent.classify_batch()` processes the utterances
- **Then:** all 30 utterances have `is_relevant` (bool) and `filter_reason` (string 1–200 chars) written to DB-1

**T41.2 — On-topic student question is RETAINED**
- **Given:** a student utterance "Can you explain eigenvalues again?" during a Linear Algebra session
- **When:** A1 classifies this utterance
- **Then:** `is_relevant=true`, confirming the filter does not discard student questions just because they are from students

**T41.3 — Off-topic lecturer aside is DISCARDED**
- **Given:** a lecturer utterance "Let me check the weather before we continue" during a Linear Algebra session
- **When:** A1 classifies this utterance
- **Then:** `is_relevant=false` with a reason indicating off-topic

**T41.4 — Discarded utterances remain in DB, not deleted**
- **Given:** an utterance classified as `is_relevant=false`
- **When:** querying the `utterances` table for that utterance's ID
- **Then:** the row exists with `is_relevant=false` and `filter_reason` populated (FR-2.15)

**T41.5 — Rationale is machine-readable**
- **Given:** a batch of utterances classified by A1
- **When:** parsing `filter_reason` for all results
- **Then:** each `filter_reason` conforms to a parseable format (e.g., JSON-encodable, contains category keyword)

**T41.6 — Batch boundaries do not change individual decisions**
- **Given:** 20 utterances classified in one batch of 20, then re-classified in two batches of 10
- **When:** comparing individual `is_relevant` decisions
- **Then:** all 20 decisions are identical regardless of batch grouping

**Verification Commands:**
```bash
# Full local verification
uv run pytest tests/test_a1_relevance.py -v -k "S41 or a1_relevance" && \
uv run mypy --strict src/services/agents/a1/ && \
uv run ruff check src/services/agents/a1/
```

**Exit Criteria:**
- [ ] T41.1 passes — every utterance receives a decision and rationale
- [ ] T41.2 passes — on-topic student questions are retained
- [ ] T41.3 passes — off-topic lecturer asides are discarded
- [ ] T41.4 passes — discarded utterances remain in DB (soft delete)
- [ ] T41.5 passes — rationale is machine-readable for threshold tuning
- [ ] T41.6 passes — batch boundaries do not change individual decisions

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- A1 prompt must include outlier score as a feature, not a gate — models that see the score as a hard threshold will over-discard
- Filtering is topic-based: a student asking "Can you repeat that?" on-topic must be retained, regardless of speaker
- `filter_reason` must be machine-readable for S42 threshold calibration — free-text reasons break the evaluation pipeline
- Batch construction must be deterministic — re-running the same batch must produce identical prompts
- LLM output may not perfectly follow JSON schema — use grammar-constrained decoding (S38) or bounded retry

**Fallback Instructions:**
- If A1 LLM call fails: retry once with exponential backoff; if still fails, leave utterances as `is_relevant=NULL` and alert
- If LLM output is malformed: bounded retry (1 attempt) via S38 schema validation
- If batch size causes context overflow: split into sub-batches of `A1_MAX_BATCH_SIZE` and merge results

**Rollback Procedure:**
- No feature flag needed — A1 only writes to existing DB-1 columns
- To undo: `UPDATE utterances SET is_relevant=NULL, filter_reason=NULL WHERE session_id=<id>`
- No schema migration required — columns already exist in DB-1

---

### 9. Observability (if applicable)

**Metrics Added:**
- `a1_batch_total`: counter of batches processed (labels: status=success/error/partial)
- `a1_utterance_classified_total`: counter of utterances classified (labels: decision=keep/discard, speaker=lecturer/student)
- `a1_classification_latency_seconds`: histogram of LLM call latency per batch
- `a1_discard_rate`: gauge of discard rate (rolling window)
- `a1_confidence_histogram`: histogram of classification confidence scores

**Tracing/Logging:**
- Span: `a1.classify_batch` with attributes (session_id, num_utterances, topic_id, latency_ms)
- Log: INFO on batch completion with keep/discard counts
- Log: WARNING on partial results or retries
- Log: ERROR on LLM failure or malformed output

**Alerts:**
- Discard rate > 50% over 10 batches: possible topic misconfiguration or prompt drift
- A1 latency P95 > 30s: LLM serving issue, check S36 health
- Partial result rate > 5%: LLM output quality issue

---

### 10. Exit Checklist

- [ ] All tests pass (T41.1, T41.2, T41.3, T41.4, T41.5, T41.6)
- [ ] A1 processes batches symmetrically across lecturer and student utterances
- [ ] Soft-delete writes are correct: `is_relevant` and `filter_reason` populated
- [ ] Rationale format is machine-readable for S42 threshold calibration
- [ ] No utterance rows are ever deleted — only marked
