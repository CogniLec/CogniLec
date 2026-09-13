# S57 — A5 Question Generation & Answerability Check
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Implement A5 agent that generates questions, quizzes, and mock tests with configurable count, difficulty, and topic coverage, using answerability check via consensus (different model attempts each question using only stored notes) to discard unanswerable questions.

**Component Boundaries:**
- **Allowed:** `src/agents/a5/`, `src/services/retrieval/` (client only), `src/db/repositories/`, `tests/test_a5_question_gen.py`, `config/prompts/a5.yaml`, `src/api/routes/assessment.py`
- **Off-limits:** RetrievalService implementation (S55), A3 agent (S56), flashcard/export logic (S58)

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| LangGraph | 0.2.x | Agent orchestration |
| LangFuse | 0.40.x | Prompt versioning + tracing |
| Pydantic | 2.13.5 | Output schemas |
| LiteLLM | 1.x | Multi-model routing for consensus |
| pytest | 8.x | Integration tests |
| testcontainers | 4.6.x | PostgreSQL for integration tests |

---

### 2. State Machine & Domain Schemas

**A5 Question Generation Flow:**
```
topic_config → generate_questions → raw_questions
             → answerability_check (different model) → verified_questions
             → filter_unanswerable → final_questions
```

**A5 Input Schema:**
```python
# src/agents/a5/models.py
from pydantic import BaseModel, Field
from uuid import UUID
from enum import Enum


class QuestionType(str, Enum):
    MCQ = "mcq"  # Multiple choice
    SHORT_ANSWER = "short_answer"
    TRUE_FALSE = "true_false"
    FILL_BLANK = "fill_blank"


class DifficultyLevel(str, Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class QuestionConfig(BaseModel):
    subject_id: UUID
    topic_ids: list[UUID] = Field(default_factory=list)
    question_type: QuestionType = QuestionType.MCQ
    count: int = Field(default=10, ge=1, le=100)
    difficulty: DifficultyLevel = DifficultyLevel.MEDIUM
    topic_coverage: float = Field(default=0.8, ge=0.0, le=1.0)


class A5Input(BaseModel):
    config: QuestionConfig
    session_ids: list[UUID] = Field(default_factory=list)  # optional session scope
    include_notes: bool = Field(default=True)  # use notes or raw transcript
```

**A5 Output Schema:**
```python
class AnswerOption(BaseModel):
    option_id: str = Field(..., pattern="^[A-D]$")
    text: str = Field(..., max_length=500)
    is_correct: bool


class Question(BaseModel):
    id: UUID
    question_type: QuestionType
    difficulty: DifficultyLevel
    text: str = Field(..., max_length=2000)
    options: list[AnswerOption] = Field(default_factory=list)  # for MCQ
    correct_answer: str = Field(..., max_length=1000)
    explanation: str = Field(..., max_length=1000)
    source_evidence: str = Field(..., max_length=500)  # from notes
    topic_id: UUID | None = None
    confidence: float = Field(..., ge=0.0, le=1.0)


class A5Output(BaseModel):
    questions: list[Question]
    total_generated: int = Field(..., ge=0)
    total_verified: int = Field(..., ge=0)
    discarded_count: int = Field(..., ge=0)
    config_used: QuestionConfig
    latency_ms: int = Field(..., ge=0)


# Answerability Check Schemas
class AnswerabilityRequest(BaseModel):
    question: Question
    context: str  # stored notes for the topic


class AnswerabilityResult(BaseModel):
    question_id: UUID
    model_used: str
    was_able_to_answer: bool
    answer_given: str = Field(default="")
    confidence: float = Field(..., ge=0.0, le=1.0)
    reasoning: str = Field(..., max_length=500)
```

**Answerability Check Flow:**
```
raw_question → send to DIFFERENT model (not the generator) →
  model attempts answer using ONLY stored notes →
  if model cannot answer → discard question
  if model answers with low confidence → flag for review
  if model answers confidently → keep question
```

**State Transition Rules:**
- Questions generated with one model, verified with a different model (consensus)
- Answerability check uses only stored notes — no access to original transcript
- Questions below answerability confidence (0.5) are discarded
- Difficulty setting affects question character (verified by human review)

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Create `src/agents/a5/models.py` with Pydantic schemas | Import succeeds, mypy passes |
| 2 | Create `src/agents/a5/prompt.py` with LangFuse prompt loading | Prompt loads correctly |
| 3 | Create `src/agents/a5/answerability.py` with consensus check | Unit test: different model attempts answer |
| 4 | Implement `A5Agent` class with LangGraph node | Agent instantiation succeeds |
| 5 | Implement question generation with topic coverage | T57.1: questions generated for requested topics |
| 6 | Implement answerability filter | T57.2, T57.3: unanswerable questions discarded |
| 7 | Add read-only DB access enforcement | T57.4: write attempt rejected |
| 8 | Add A3 isolation enforcement | T57.5: no A3 calls in traces |
| 9 | Add difficulty setting verification | T57.6: difficulty changes question character |
| 10 | Write integration tests | All T57.x tests pass |

**Atomic Sub-tasks:**
1. A5 output schemas (Question, A5Output, AnswerabilityResult)
2. A5 prompt versioning with LangFuse
3. Answerability check with different model (consensus)
4. A5 agent implementation with LangGraph
5. Question generation with configurable count/difficulty/coverage
6. Assessment API endpoint
7. Integration and performance test suite

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| No topics found for subject | Return empty questions, log warning |
| All questions fail answerability check | Return empty with discarded_count |
| Consensus model unavailable | Skip answerability check, flag all questions for review |
| Topic coverage impossible (too few notes) | Generate questions from available notes, log coverage |
| Difficulty setting affects answerability | Adjust difficulty per topic availability |
| 20 questions in < 30s requirement | Monitor latency, optimize prompt or batch |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Agent pattern: A5 as LangGraph node with structured output
- Consensus pattern: different model for answerability check
- Pipeline pattern: generate → verify → filter
- Prompt versioning: LangFuse for prompt management

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase (`A5Agent`, `Question`, `AnswerabilityResult`)
- Files: snake_case (`a5_agent.py`, `answerability.py`, `question_generator.py`)
- Functions: snake_case (`generate_questions`, `check_answerability`)
- Constants: UPPER_SNAKE_CASE

**Code Splitting Metrics:**
- Max function length: 40 lines
- Max file length: 300 lines
- Max class methods: 10

**Type Safety:**
- All function signatures typed with Pydantic v2 models
- `from __future__ import annotations` in all files
- UUID type hints for all ID parameters
- QuestionType and DifficultyLevel enums enforced at schema level

---

### 5. API & Interface Contracts

**Internal API:**
```python
# src/agents/a5/agent.py
class A5Agent:
    def __init__(
        self,
        retrieval_service: RetrievalService,
        llm_router: LiteLLMRouter,  # for multi-model consensus
        db_session: AsyncSession,  # read-only
        prompt_version: str = "1.0.0",
    ): ...

    async def run(self, input: A5Input) -> A5Output:
        """Generate questions with answerability check. Read-only DB access."""
        ...

    async def _generate_questions(self, config: QuestionConfig, context: str) -> list[Question]:
        """Generate questions from context using LLM."""
        ...

    async def _check_answerability(
        self, questions: list[Question], notes_context: str
    ) -> list[AnswerabilityResult]:
        """Check answerability using a different model (consensus)."""
        ...

    def _filter_verified_questions(
        self,
        questions: list[Question],
        results: list[AnswerabilityResult],
        min_confidence: float = 0.5,
    ) -> list[Question]:
        """Filter questions that passed answerability check."""
        ...
```

**Assessment API Endpoint:**
```python
# src/api/routes/assessment.py
@router.post("/api/v1/assessment/generate", response_model=A5Output)
async def generate_assessment(
    config: QuestionConfig,
    session_ids: list[UUID] | None = None,
    current_user: User = Depends(get_current_user),
    a5_agent: A5Agent = Depends(get_a5_agent),
) -> A5Output:
    """Generate assessment questions for a subject."""
    ...


@router.get("/api/v1/assessment/{session_id}", response_model=A5Output)
async def get_assessment(
    session_id: UUID,
    current_user: User = Depends(get_current_user),
) -> A5Output:
    """Retrieve generated assessment for a session."""
    ...
```

**Mock Request/Response Payloads:**
```json
// POST /api/v1/assessment/generate
// Request:
{
  "config": {
    "subject_id": "550e8400-e29b-41d4-a716-446655440000",
    "topic_ids": ["770e8400-e29b-41d4-a716-446655440002"],
    "question_type": "mcq",
    "count": 10,
    "difficulty": "medium",
    "topic_coverage": 0.8
  },
  "session_ids": ["660e8400-e29b-41d4-a716-446655440001"],
  "include_notes": true
}

// Response 200:
{
  "questions": [
    {
      "id": "...",
      "question_type": "mcq",
      "difficulty": "medium",
      "text": "Which optimization algorithm adapts learning rates per parameter?",
      "options": [
        {"option_id": "A", "text": "SGD", "is_correct": false},
        {"option_id": "B", "text": "Adam", "is_correct": true},
        {"option_id": "C", "text": "Batch GD", "is_correct": false},
        {"option_id": "D", "text": "Newton's Method", "is_correct": false}
      ],
      "correct_answer": "B",
      "explanation": "Adam maintains per-parameter learning rates using first and second moment estimates.",
      "source_evidence": "Adam optimizer adapts learning rates per parameter using moving averages of gradients.",
      "topic_id": "...",
      "confidence": 0.92
    }
  ],
  "total_generated": 12,
  "total_verified": 10,
  "discarded_count": 2,
  "config_used": {...},
  "latency_ms": 24000
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
| `EMBEDDING_ENDPOINT` | string | TEI embedding endpoint | `http://tei:80` |
| `LITELLM_PROXY_URL` | string | LiteLLM proxy for multi-model routing | `http://litellm:4000` |
| `LANGFUSE_PUBLIC_KEY` | string | LangFuse public key | — |
| `LANGFUSE_SECRET_KEY` | string | LangFuse secret key | — |
| `A5_PROMPT_VERSION` | string | A5 prompt version | `1.0.0` |
| `A5_ANSWERABILITY_MODEL` | string | Model for answerability check (different from generator) | `gpt-4o-mini` |
| `A5_ANSWERABILITY_CONFIDENCE` | float | Minimum confidence for answerability | `0.5` |
| `A5_GENERATOR_MODEL` | string | Model for question generation | `tier_1_local` |

**Third-Party Integration Contracts:**
- RetrievalService (S55): stateless retrieval with hybrid recall + rerank
- LiteLLMRouter: multi-model routing for consensus (generator vs verifier)
- LangFuse: prompt versioning, tracing, agent_runs audit
- LangGraph: agent orchestration, structured output

**Version Pins:**
- `litellm` pinned in `pyproject.toml`
- `langgraph` pinned in `pyproject.toml`
- `langfuse` pinned in `pyproject.toml`
- A5 prompt version pinned in `config/prompts/a5.yaml`

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T57.1 | I | `pytest tests/test_a5_question_gen.py::test_questions_generated -v` | Questions generated for requested topics at requested count |
| T57.2 | I | `pytest tests/test_a5_question_gen.py::test_answerable_from_notes -v` | Generated questions are answerable from stored notes |
| T57.3 | V | `pytest tests/test_a5_question_gen.py::test_answerability_filter -v` | Answerability check discards measurable fraction of bad questions |
| T57.4 | S | `pytest tests/test_a5_question_gen.py::test_readonly_db_access -v` | Write attempt rejected at database level |
| T57.5 | I | `pytest tests/test_a5_question_gen.py::test_no_a3_communication -v` | No A3↔A5 communication in traces |
| T57.6 | I | `pytest tests/test_a5_question_gen.py::test_difficulty_changes -v` | Difficulty setting changes question character |
| T57.7 | P | `pytest tests/test_a5_question_gen.py::test_20_questions_perf -v` | 20-question test generated in < 30s |

**Test Case Details (Given/When/Then):**

**T57.1 — Questions generated for requested topics**
- **Given:** a subject with 5 topics, config requesting 10 MCQ questions at medium difficulty
- **When:** A5Agent.run() is called with the config
- **Then:** output contains 10 questions, each with valid MCQ options, covering the requested topics

**T57.2 — Generated questions answerable from notes**
- **Given:** 20 generated questions and the source notes
- **When:** each question is answered using ONLY the source notes
- **Then:** ≥ 90% of questions can be answered correctly from the notes (AC-19)

**T57.3 — Answerability check discards bad questions**
- **Given:** 20 questions, some deliberately unanswerable from notes
- **When:** answerability check runs with a different model
- **Then:** unanswerable questions are discarded; discarded_count > 0

**T57.4 — Read-only DB access**
- **Given:** A5Agent is instantiated with a DB connection configured as read-only
- **When:** agent attempts to write (INSERT/UPDATE/DELETE) — simulated by the test
- **Then:** database rejects the write with a permission error

**T57.5 — No A3↔A5 communication**
- **Given:** A5Agent is run with tracing enabled
- **When:** execution trace is inspected
- **Then:** no calls to A3 appear in the trace; no shared state with A3

**T57.6 — Difficulty setting changes question character**
- **Given:** same topic content, difficulty set to "easy" and "hard"
- **When:** A5Agent.run() is called twice with different difficulty settings
- **Then:** "easy" questions are simpler (definitions, recall); "hard" questions are complex (analysis, application)

**T57.7 — 20-question performance**
- **Given:** a subject with sufficient content for 20 questions
- **When:** A5Agent.run() is called with count=20
- **Then:** total latency (generate + verify) is < 30s (NFR-P5)

**Verification Commands:**
```bash
# Full local verification
uv run pytest tests/test_a5_question_gen.py -v -k "S57 or a5_question" && \
uv run mypy --strict src/agents/a5/ && \
uv run ruff check src/agents/a5/
```

**Exit Criteria:**
- [ ] T57.1 passes — questions generated for requested topics
- [ ] T57.2 passes — generated questions answerable from notes
- [ ] T57.3 passes — answerability check discards bad questions
- [ ] T57.4 passes — read-only DB access enforced
- [ ] T57.5 passes — no A3↔A5 communication in traces
- [ ] T57.6 passes — difficulty setting changes question character
- [ ] T57.7 passes — 20-question test generated in < 30s

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- Consensus model must be different from generator — otherwise it validates its own output
- Answerability check is the strongest application of multi-model — don't skip it
- Topic coverage requires retrieval to work correctly — check retrieval quality first
- Difficulty calibration requires human verification — can't be fully automated
- Performance target (30s for 20 questions) requires efficient batching

**Fallback Instructions:**
- If consensus model unavailable: skip answerability check, flag all questions for review
- If question count not met: reduce topic coverage or difficulty, log warning
- If performance target missed: optimize prompt, batch questions, check retrieval latency
- If difficulty doesn't change: check prompt, verify model is receiving difficulty parameter

**Rollback Procedure:**
- Disable A5 in pipeline: remove A5 node from LangGraph workflow
- Disable answerability check: set `A5_ANSWERABILITY_ENABLED=false`
- No database migrations required
- Assessment API returns 503 when A5 disabled

---

### 9. Observability (if applicable)

**Metrics Added:**
- `a5_questions_generated_total`: counter of questions generated
- `a5_questions_verified_total`: counter of questions that passed answerability
- `a5_questions_discarded_total`: counter of questions discarded by answerability check
- `a5_latency_seconds`: histogram of A5 execution latency (generate + verify)
- `a5_answerability_confidence`: histogram of answerability confidence scores

**Tracing/Logging:**
- Span: `a5.run` with child spans for generation, answerability, filtering
- Log: INFO on questions generated/verified/discarded with counts
- Log: DEBUG on answerability check results per question
- Log: WARNING on low answerability rate (> 50% discarded)

**Alerts:**
- Answerability discard rate > 50%: investigate note quality or prompt issues
- A5 latency > 30s for 20 questions: check retrieval or model performance
- No questions generated for a session: investigate retrieval quality

---

### 10. Exit Checklist

- [ ] All tests pass (T57.1–T57.7)
- [ ] Questions generated for requested topics at requested count
- [ ] Generated questions answerable from stored notes (AC-19)
- [ ] Answerability check discards measurable fraction of bad questions
- [ ] Read-only DB access enforced at database level
- [ ] No A3↔A5 communication in traces (AC-15)
- [ ] Difficulty setting changes question character
- [ ] 20-question test generated in < 30s (NFR-P5)
