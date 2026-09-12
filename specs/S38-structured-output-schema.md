# S38 — Structured Output & Schema Registry
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Guarantee all agent outputs are schema-valid or explicitly failed by implementing grammar-constrained decoding on local models and bounded retry on hosted tiers.

**Component Boundaries:**
- **Allowed:** `src/services/llm/schema_registry.py`, `src/services/llm/output_validator.py`, `config/schemas/`, `tests/test_schema_registry.py`
- **Off-limits:** Router failover logic (S37), observability (S39), agent implementations (S56–S57)

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| Outlines / XGrammar | latest | Grammar-constrained decoding for local models |
| Instructor | 1.x | Structured output for hosted API models |
| Pydantic | 2.x | Schema definitions |
| pytest | 8.x | Integration tests |

---

### 2. State Machine & Domain Schemas

**Schema Validation Flow:**
```
local_model → grammar约束 → output is structurally valid JSON (impossible to be invalid)
hosted_model → instructor_validate → pass OR retry_once → pass OR failover
```

**Pydantic Models:**
```python
# src/services/llm/schema_registry.py
from pydantic import BaseModel, Field
from enum import Enum

class AgentID(str, Enum):
    A1 = "A1"  # Concept Tutor
    A2 = "A2"  # Problem Coach
    A3 = "A3"  # Socratic Guide
    A4 = "A4"  # Study Planner
    A5 = "A5"  # Exam Sim
    A6 = "A6"  # Progress Analyst

class SchemaEntry(BaseModel):
    agent_id: AgentID
    schema_name: str
    schema: dict  # JSON Schema or Pydantic model reference
    version: str
    grammar_path: str | None = None  # compiled grammar for local models
    last_updated: str

class SchemaRegistry(BaseModel):
    schemas: dict[AgentID, SchemaEntry]
    version: str

class ValidationFailure(BaseModel):
    agent_id: AgentID
    raw_output: str
    error_message: str
    tier: str
    attempt: int
    timestamp: str
```

**Agent Output Schemas:**
```python
# src/services/llm/schemas/a1_concept_tutor.py
from pydantic import BaseModel, Field

class A1Output(BaseModel):
    explanation: str = Field(..., min_length=10, max_length=2000)
    key_concepts: list[str] = Field(..., min_length=1, max_length=10)
    difficulty: str = Field(..., pattern="^(easy|medium|hard)$")
    follow_up_question: str | None = Field(None, max_length=500)
    confidence: float = Field(..., ge=0.0, le=1.0)

# src/services/llm/schemas/a3_socratic_guide.py
class A3Output(BaseModel):
    response_type: str = Field(..., pattern="^(hint|question|feedback|corrective)$")
    content: str = Field(..., min_length=5, max_length=1500)
    student_reasoning_assessment: str = Field(..., pattern="^(correct|partial|misconception|empty)$")
    next_prompt_strategy: str = Field(..., pattern="^(scaffold|probe|redirect|confirm)$")

# src/services/llm/schemas/a5_exam_sim.py
class A5Output(BaseModel):
    question: str = Field(..., min_length=10, max_length=2000)
    question_type: str = Field(..., pattern="^(mcq|short_answer|essay|true_false)$")
    options: list[str] | None = Field(None, min_length=2, max_length=6)
    correct_answer: str = Field(..., min_length=1)
    explanation: str = Field(..., min_length=10, max_length=1000)
    difficulty: str = Field(..., pattern="^(easy|medium|hard)$")
    topic_tags: list[str] = Field(..., min_length=1, max_length=5)
```

**State Transition Rules:**
- Local model: grammar constraint ensures output is always valid JSON — no validation failure path
- Hosted model: output parsed → valid → return; invalid → one retry with error context → valid → return; invalid → failover
- Schema missing for agent: CI fails, block merge

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Define Pydantic schemas for all agents A1–A6 in `config/schemas/` | All schemas import without error |
| 2 | Build `SchemaRegistry` that loads and validates all schemas at startup | Registry loads 6 schemas, CI fails if any missing |
| 3 | Integrate Outlines/XGrammar grammar compilation for local model schemas | Grammar files generated for Tier 1 model |
| 4 | Integrate Instructor with bounded retry for hosted tier schemas | Hosted output validated, 1 retry on failure |
| 5 | Wire validation failure logging with raw output for debugging | Failure log contains agent_id, raw_output, error |
| 6 | Add CI check: all agents must have registered schemas | CI fails if schema missing (T38.3) |
| 7 | Add CI check: schema changes flagged as breaking-change warning | CI warns on schema modification (T38.4) |
| 8 | Run 500-generation test for local model schema validity | T38.1: all outputs schema-valid |

**Atomic Sub-tasks:**
1. Pydantic schema definitions for A1–A6
2. SchemaRegistry with startup validation
3. Outlines/XGrammar grammar compilation for local models
4. Instructor integration for hosted tiers with bounded retry
5. Validation failure logging
6. CI gate: schema completeness and breaking-change detection

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| Schema missing for agent | CI fails, block merge |
| Local model produces non-JSON | Impossible with grammar constraint; log and alert if ever occurs |
| Hosted model schema invalid | One bounded retry with error context, then failover |
| Schema changed without version bump | CI warns as breaking change |
| Schema registry fails to load | Service fails to start — fail fast |
| Output exceeds max length | Truncate and log, then validate truncated output |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Registry pattern: `SchemaRegistry` centralizes all agent schemas
- Strategy pattern: grammar constraint (local) vs. Instructor retry (hosted)
- Validator pattern: `OutputValidator` wraps validation logic

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase
- Files: snake_case (`schema_registry.py`, `a1_concept_tutor.py`)
- Schema files: one per agent in `config/schemas/`

**Code Splitting Metrics:**
- Max function length: 40 lines
- Max file length: 300 lines
- One schema class per file

**Type Safety:**
- All schemas are Pydantic v2 models with strict field types
- `from __future__ import annotations` in all files
- Enum types for agent IDs and fixed-choice fields

---

### 5. API & Interface Contracts

**Schema Registry Interface:**
```python
# src/services/llm/schema_registry.py
class SchemaRegistry:
    def get_schema(self, agent_id: AgentID) -> SchemaEntry:
        """Get schema for an agent. Raises ValueError if missing."""
        ...

    def validate_output(self, agent_id: AgentID, output: str) -> dict:
        """Validate output against agent schema. Returns parsed dict or raises."""
        ...

    def get_grammar(self, agent_id: AgentID) -> str | None:
        """Get compiled grammar for local model constrained decoding."""
        ...

    def list_schemas(self) -> list[SchemaEntry]:
        """List all registered schemas."""
        ...
```

**Output Validator Interface:**
```python
# src/services/llm/output_validator.py
class OutputValidator:
    async def validate(
        self,
        agent_id: AgentID,
        raw_output: str,
        tier: LLMTier,
    ) -> dict:
        """
        Validate output. For local tiers, grammar guarantees validity.
        For hosted tiers, Instructor validates with 1 retry.
        Returns parsed dict or raises ValidationFailure.
        """
        ...
```

**Schema File Format (`config/schemas/a1.json`):**
```json
{
  "agent_id": "A1",
  "schema_name": "concept_tutor_output",
  "version": "1.0.0",
  "schema": {
    "type": "object",
    "properties": {
      "explanation": {"type": "string", "minLength": 10, "maxLength": 2000},
      "key_concepts": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 10},
      "difficulty": {"type": "string", "enum": ["easy", "medium", "hard"]},
      "follow_up_question": {"type": ["string", "null"], "maxLength": 500},
      "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0}
    },
    "required": ["explanation", "key_concepts", "difficulty", "confidence"],
    "additionalProperties": false
  }
}
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Default |
|----------|------|-------------|---------|
| `SCHEMA_DIR` | string | Path to schema definitions | `config/schemas/` |
| `OUTLINES_CACHE_DIR` | string | Compiled grammar cache | `/tmp/outlines_grammar` |
| `INSTRUCTOR_MAX_RETRIES` | int | Max retries for hosted tier validation | `1` |
| `SCHEMA_VALIDATION_ENABLED` | bool | Feature flag for validation | `true` |

**Third-Party Integration Contracts:**
- Outlines/XGrammar: grammar compilation API for local models
- Instructor: wraps OpenAI/Anthropic clients for structured output

**Version Pins:**
- Outlines/XGrammar pinned in `pyproject.toml`
- Instructor pinned in `pyproject.toml`

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T38.1 | I | `pytest tests/test_schema_registry.py::test_local_model_500_generations -v` | 500 varied local model outputs are all schema-valid |
| T38.2 | I | `pytest tests/test_schema_registry.py::test_hosted_malformed_retry -v` | Malformed hosted response triggers exactly 1 retry, then failover |
| T38.3 | U | `pytest tests/test_schema_registry.py::test_all_agents_have_schemas -v` | Every agent A1–A6 has a registered schema |
| T38.4 | U | `pytest tests/test_schema_registry.py::test_schema_change_detected -v` | Schema change flagged as breaking-change warning in CI |
| T38.5 | I | `pytest tests/test_schema_registry.py::test_validation_failure_logged -v` | Schema failure logged with offending output |

**Test Case Details (Given/When/Then):**

**T38.1 — Local model output always schema-valid**
- **Given:** Tier 1 local model with grammar constraint for A1 schema
- **When:** 500 varied generation prompts are sent
- **Then:** all 500 outputs parse as valid JSON matching the A1 schema

**T38.2 — Hosted tier malformed response retry + failover**
- **Given:** a hosted tier model that returns malformed JSON on first attempt
- **When:** `OutputValidator.validate()` is called
- **Then:** exactly 1 retry is attempted; if still invalid, failover is triggered

**T38.3 — All agents have registered schemas**
- **Given:** the schema registry is loaded at CI startup
- **When:** the registry is queried for agents A1–A6
- **Then:** all 6 agents have schemas; CI fails if any are missing

**T38.4 — Schema change detected by CI**
- **Given:** a committed schema file with version 1.0.0
- **When:** a field is added or type changed without bumping version
- **Then:** CI outputs a breaking-change warning and optionally blocks merge

**T38.5 — Validation failure logged with output**
- **Given:** a hosted model returns output that fails schema validation
- **When:** the validator processes the output
- **Then:** a log entry contains agent_id, raw_output, error_message, tier, and attempt number

**Verification Commands:**
```bash
uv run pytest tests/test_schema_registry.py -v -k "S38 or schema" && \
uv run mypy --strict src/services/llm/ && \
uv run ruff check src/services/llm/
```

**Exit Criteria:**
- [ ] T38.1 passes — 500 local generations all schema-valid
- [ ] T38.2 passes — malformed hosted response: 1 retry then failover
- [ ] T38.3 passes — all agents A1–A6 have registered schemas
- [ ] T38.4 passes — schema changes flagged as breaking
- [ ] T38.5 passes — validation failures logged with raw output

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- Grammar compilation is slow on first run — cache compiled grammars in `OUTLINES_CACHE_DIR`
- Outlines grammar must match the model's tokenizer exactly — grammar for Phi-3 won't work on Qwen
- Instructor retry count must be bounded (exactly 1) — unbounded retry wastes hosted API credits
- Schema validation on hosted tiers adds latency — acceptable tradeoff for correctness

**Fallback Instructions:**
- If grammar compilation fails: fall back to Instructor-style validation with bounded retry
- If schema registry fails to load: service fails to start (fail-fast, no silent malformation)
- If validation blocks for > 5s: skip validation, log warning, continue (graceful degradation)

**Rollback Procedure:**
- Set `SCHEMA_VALIDATION_ENABLED=false` to disable validation entirely
- Remove Outlines integration, revert to Instructor-only validation
- No database changes — schemas are file-based

---

### 9. Observability (if applicable)

**Metrics Added:**
- `schema_validation_total`: counter (labels: agent_id, tier, status=valid/invalid/retried)
- `schema_validation_latency_seconds`: histogram
- `schema_grammar_compilation_seconds`: gauge (first-run compilation time)
- `schema_validation_failure_total`: counter (labels: agent_id, error_type)

**Tracing/Logging:**
- Span: `schema.validate` with attributes (agent_id, tier, is_valid, latency_ms)
- Log: ERROR on validation failure with full raw output for debugging
- Log: INFO on grammar compilation completion

**Alerts:**
- Validation failure rate > 5% for any agent: investigate model output quality
- Grammar compilation time > 30s: cache may be corrupted

---

### 10. Exit Checklist

- [ ] All tests pass (T38.1, T38.2, T38.3, T38.4, T38.5)
- [ ] All agents A1–A6 have Pydantic schemas registered
- [ ] Local model outputs are grammar-constrained and always valid
- [ ] Hosted model validation has bounded retry (exactly 1)
- [ ] Validation failures are logged with raw output for debugging
- [ ] CI blocks merge if any agent schema is missing
