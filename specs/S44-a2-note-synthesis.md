# S44 — A2 Note Synthesis
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** A2 receives the full session transcript plus all segments plus prior session notes plus syllabus context in one call, emits structured sections with heading, `body_md`, depth, ordinal, and `source_utt_ids` for provenance — preferring Mermaid/KaTeX over requesting an image.

**Component Boundaries:**
- **Allowed:** `src/services/agents/a2/`, `config/prompts/a2_synthesis/`, `tests/test_a2_synthesis.py`
- **Off-limits:** A1 filtering (S41–S43), note persistence (S45), note API (S46), image retrieval (S62)

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| Local LLM | Tier 1 (S36) | Primary inference for synthesis |
| Pydantic | 2.x | Schema definitions for A2 output |
| Mermaid | 10.x | Diagram rendering validation |
| KaTeX | 0.16.x | Math rendering validation |
| pytest | 8.x | Integration tests |

---

### 2. State Machine & Domain Schemas

**A2 Synthesis Flow:**
```
full_session_transcript + segments + prior_notes + syllabus
  → single LLM call (v2.0 §3.2)
  → structured sections output
  → validation (hierarchy, ordering, provenance)
  → note_sections + note_provenance ready for persistence (S45)
```

**Full-Context Approach (v2.0 §3.2):**
- A2 receives ALL data in one call (not segment-by-segment)
- Justified: local GPUs make this cheap, and cross-segment coherence improves quality
- Prior session notes provide continuity across sessions
- Syllabus context ensures alignment with curriculum

**A2 Output Schema:**
```python
# src/services/agents/a2/models.py
from pydantic import BaseModel, Field

class NoteSection(BaseModel):
    heading: str = Field(..., min_length=1, max_length=200)
    body_md: str = Field(..., min_length=1)
    depth: int = Field(..., ge=0, le=5)  # heading hierarchy depth
    ordinal: int = Field(..., ge=0)      # ordering within depth level
    source_utt_ids: list[str] = Field(..., min_length=1)  # FR-7.8: every section needs provenance
    has_mermaid: bool = False            # whether body contains Mermaid blocks
    has_katex: bool = False              # whether body contains KaTeX math

class A2SynthesisResult(BaseModel):
    session_id: str
    topic_id: str | None = None
    sections: list[NoteSection] = Field(..., min_length=1)
    model: str
    prompt_version: str
    total_source_utterances: int
```

**State Transition Rules:**
- A2 receives pre-filtered utterances (only `is_relevant=true` from S41)
- A2 emits sections with provenance linking back to source utterances
- Every section must have at least one `source_utt_id` (FR-7.8)
- All `source_utt_ids` must reference utterances marked `is_relevant=true`
- No discarded utterance content may appear in notes
- Mermaid/KaTeX preferred over image requests (v1.1 §20, D-25)

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Define A2 output Pydantic schema in `src/services/agents/a2/models.py` | Schema imports, validates sample output |
| 2 | Create A2 prompt template in `config/prompts/a2_synthesis/v1.md` with full-context input | Prompt loads from versioned registry |
| 3 | Implement `A2SynthesisAgent` class with `synthesize()` method | Unit test: mock LLM returns valid sections |
| 4 | Implement full-context prompt builder (transcript + segments + prior notes + syllabus) | Unit test: prompt contains all required context |
| 5 | Implement section hierarchy and ordering validation | T44.1 passes |
| 6 | Implement provenance validation (every section has source utterance IDs) | T44.2, T44.3 pass |
| 7 | Implement Mermaid/KaTeX syntax validation | T44.6, T44.7 pass |
| 8 | Implement discarded-utterance content exclusion | T44.8 passes |
| 9 | Run human review evaluation | T44.4, T44.5 pass |
| 10 | Run full integration test suite | All tests pass |

**Atomic Sub-tasks:**
1. A2 output Pydantic schema definition
2. Versioned prompt template with full-context input structure
3. Full-context prompt builder (transcript + segments + prior notes + syllabus)
4. `A2SynthesisAgent.synthesize()` implementation
5. Section hierarchy and ordering validation
6. Provenance validation (source utterance ID existence and relevance)
7. Mermaid/KaTeX syntax validation
8. Discarded-utterance content exclusion logic
9. Human review evaluation framework

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| Session has zero relevant utterances after filtering | Return empty sections list, log warning |
| Prior session notes unavailable | Omit from prompt, proceed without |
| Syllabus not loaded | Omit from prompt, proceed without |
| LLM output exceeds context window | Truncate transcript to most recent segments, log |
| Provenance ID references discarded utterance | Reject section, log error, re-synthesize |
| Mermaid block has syntax error | Log warning, include raw block (renderer will show error) |
| KaTeX block has render error | Log warning, include raw block |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Agent pattern: `A2SynthesisAgent` encapsulates synthesis logic
- Builder pattern: `FullContextPromptBuilder` assembles prompt from components
- Validator pattern: `SectionValidator` checks hierarchy, ordering, provenance
- Strategy pattern: prompt versioned via registry (S40)

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase (`A2SynthesisAgent`, `A2SynthesisResult`)
- Files: snake_case (`a2_synthesis.py`, `models.py`)
- Functions: snake_case (`synthesize`, `validate_sections`)
- Constants: UPPER_SNAKE_CASE (`MAX_SECTION_DEPTH`)

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

**A2 Synthesis Agent Interface:**
```python
# src/services/agents/a2/synthesis.py
class A2SynthesisAgent:
    def __init__(self, llm_client, prompt_registry, utterance_repo, note_repo):
        ...

    async def synthesize(
        self,
        session_id: UUID,
        subject_id: UUID,
        topic_id: UUID | None,
        topic_description: str,
    ) -> A2SynthesisResult:
        """Synthesize notes from full session context.

        Receives all relevant utterances, segments, prior notes, and syllabus.
        Returns structured sections with provenance.
        """
        ...

    async def _build_full_context(
        self,
        session_id: UUID,
        subject_id: UUID,
        topic_id: UUID | None,
    ) -> str:
        """Assemble full-context prompt from all data sources."""
        ...
```

**Full-Context Prompt Template (`config/prompts/a2_synthesis/v1.md`):**
```markdown
# A2 Note Synthesis

You are a lecture note synthesizer. Create structured, accurate notes from the
following lecture session.

## Syllabus Context
{{syllabus_context}}

## Prior Session Notes
{{#if prior_notes}}
{{prior_notes}}
{{else}}
No prior notes available.
{{/if}}

## Session Transcript (Filtered — Only Relevant Utterances)
{{#each utterances}}
[{{speaker_tag}}] (utt:{{id}}, topic:{{topic_id}}):
{{text}}
{{/each}}

## Segment Boundaries
{{#each segments}}
Segment {{ordinal}}: utterances {{start_utt}} → {{end_utt}} (topic: {{topic_id}})
{{/each}}

## Output Format (JSON)
{
  "sections": [
    {
      "heading": "Section Title",
      "body_md": "Markdown content with **bold**, *italic*, and $$math$$...",
      "depth": 0,
      "ordinal": 0,
      "source_utt_ids": ["uuid-utt-1", "uuid-utt-2"],
      "has_mermaid": false,
      "has_katex": false
    }
  ]
}

## Rules
1. Every section MUST have at least one source_utt_id (provenance)
2. source_utt_ids must reference utterances from the transcript above
3. Use Mermaid for diagrams: ```mermaid blocks
4. Use KaTeX for math: $$ inline $$ or $$ block $$
5. Do NOT request images — prefer Mermaid/KaTeX
6. Sections must have hierarchical depth (0 = top level)
7. Ordinal must be sequential within each depth level
8. Do NOT include content from filtered-out utterances
```

**Section Validator Interface:**
```python
# src/services/agents/a2/validator.py
class SectionValidator:
    def validate_hierarchy(self, sections: list[NoteSection]) -> list[str]:
        """Validate depth hierarchy. Returns list of errors."""
        ...

    def validate_ordering(self, sections: list[NoteSection]) -> list[str]:
        """Validate ordinal sequencing within depth levels."""
        ...

    def validate_provenance(
        self,
        sections: list[NoteSection],
        valid_utterance_ids: set[str],
    ) -> list[str]:
        """Validate all source_utt_ids reference existing, relevant utterances."""
        ...

    def validate_no_discarded_content(
        self,
        sections: list[NoteSection],
        discarded_utterance_ids: set[str],
    ) -> list[str]:
        """Ensure no section contains content from discarded utterances."""
        ...
```

**Database Schema (output, written by S45):**
```sql
-- A2 produces data for note_sections table (S10):
-- heading, body_md, depth, ordinal, source_utt_ids
-- These are persisted by S45, not by A2 directly.
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Default |
|----------|------|-------------|---------|
| `A2_MODEL` | string | Model for A2 synthesis | `tier_1` |
| `A2_TEMPERATURE` | float | LLM temperature for A2 | `0.3` |
| `A2_MAX_SECTIONS` | int | Maximum note sections per session | `50` |
| `A2_PROMPT_VERSION` | string | Active prompt version | `v1` |
| `A2_MAX_BODY_LENGTH` | int | Max chars per section body | `5000` |

**Third-Party Integration Contracts:**
- Local LLM (S36): OpenAI-compatible endpoint
- Prompt Registry (S40): prompt loading by version reference
- Utterance Repository (S09): fetch relevant utterances
- Note Repository (S10): fetch prior session notes

**Version Pins:**
- LLM model pinned in `config/models.yaml`
- Prompt version pinned in `config/prompts/a2_synthesis/`

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T44.1 | I | `pytest tests/test_a2_synthesis.py::test_valid_hierarchy_ordering -v` | Notes produced with valid hierarchy and ordering |
| T44.2 | I | `pytest tests/test_a2_synthesis.py::test_every_section_has_provenance -v` | Every section carries at least one source_utt_id (FR-7.8) |
| T44.3 | I | `pytest tests/test_a2_synthesis.py::test_provenance_ids_valid -v` | All source_utt_ids reference utterances with `is_relevant=true` |
| T44.4 | M | Manual review: 10 sessions rated ≥ 4/5 on accuracy, completeness, structure | Human review passes target quality |
| T44.5 | V | `pytest tests/test_a2_synthesis.py::test_full_context_better_than_segment -v` | Full-context synthesis rated better than segment-by-segment |
| T44.6 | I | `pytest tests/test_a2_synthesis.py::test_mermaid_syntax_valid -v` | Emitted Mermaid blocks are syntactically valid |
| T44.7 | I | `pytest tests/test_a2_synthesis.py::test_katex_renders -v` | Emitted KaTeX renders without error |
| T44.8 | I | `pytest tests/test_a2_synthesis.py::test_no_discarded_content -v` | No discarded utterance content appears in notes |

**Test Case Details (Given/When/Then):**

**T44.1 — Notes produced with valid hierarchy and ordering**
- **Given:** a session with 30 relevant utterances across 3 topics
- **When:** `A2SynthesisAgent.synthesize()` is called
- **Then:** output sections have valid depth hierarchy (0→1→2) and sequential ordinals within each depth

**T44.2 — Every section carries at least one provenance utterance ID**
- **Given:** a synthesis result with 8 sections
- **When:** checking `source_utt_ids` for each section
- **Then:** every section has at least one non-empty `source_utt_id` (FR-7.8)

**T44.3 — Provenance IDs all reference relevant utterances**
- **Given:** a synthesis result and the set of utterances with `is_relevant=true`
- **When:** validating `source_utt_ids` against the relevant utterance set
- **Then:** all `source_utt_ids` exist in the relevant utterance set

**T44.4 — Human review: notes accurate, complete, well-structured**
- **Given:** 10 sessions with varied content types (lectures, discussions, Q&A)
- **When:** human reviewers rate notes on accuracy (1–5), completeness (1–5), structure (1–5)
- **Then:** average score across all dimensions ≥ 4/5

**T44.5 — Full-context synthesis rated better than segment-by-segment**
- **Given:** the same session processed via full-context (A2) and segment-by-segment approaches
- **When:** human reviewers compare the two note sets blind
- **Then:** full-context notes are rated as better or equal on ≥ 70% of comparisons

**T44.6 — Emitted Mermaid blocks are syntactically valid**
- **Given:** a synthesis result with Mermaid diagram blocks
- **When:** parsing each Mermaid block with a syntax validator
- **Then:** all Mermaid blocks parse without syntax errors

**T44.7 — Emitted KaTeX renders without error**
- **Given:** a synthesis result with KaTeX math blocks
- **When:** rendering each KaTeX block
- **Then:** all KaTeX blocks render without error

**T44.8 — No discarded utterance content appears in notes**
- **Given:** a synthesis result and the set of discarded utterances (`is_relevant=false`)
- **When:** checking note body content for discarded utterance text
- **Then:** no section body contains verbatim text from discarded utterances

**Verification Commands:**
```bash
# Full local verification
uv run pytest tests/test_a2_synthesis.py -v -k "S44 or a2_synthesis" && \
uv run mypy --strict src/services/agents/a2/ && \
uv run ruff check src/services/agents/a2/
```

**Exit Criteria:**
- [ ] T44.1 passes — notes have valid hierarchy and ordering
- [ ] T44.2 passes — every section has at least one provenance utterance ID
- [ ] T44.3 passes — provenance IDs reference relevant utterances
- [ ] T44.4 passes — human review ≥ 4/5 on 10 sessions
- [ ] T44.5 passes — full-context rated better than segment-by-segment
- [ ] T44.6 passes — Mermaid blocks are syntactically valid
- [ ] T44.7 passes — KaTeX renders without error
- [ ] T44.8 passes — no discarded content in notes

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- Full-context approach requires sufficient VRAM for large transcripts — if context window exceeded, truncate from oldest utterances first
- Provenance validation is critical: a section without valid source utterance IDs is unverifiable
- Mermaid/KaTeX preference is a hard constraint (v1.1 §20, D-25) — A2 must not request images
- Prior session notes may be unavailable for first sessions — prompt must handle gracefully
- Discarded utterance content exclusion must be checked — LLM may hallucinate content from filtered utterances

**Fallback Instructions:**
- If LLM output is malformed: bounded retry via S38 schema validation
- If context window exceeded: truncate transcript to most recent segments, log truncation
- If provenance IDs invalid: reject section, log error, attempt re-synthesis
- If Mermaid/KaTeX syntax invalid: log warning, include raw block (renderer shows error)

**Rollback Procedure:**
- No feature flag needed — A2 only reads from DB-1 and produces in-memory output
- To discard notes: simply do not persist (S45 handles persistence)
- Prompt changes tracked via S40 versioning — roll back prompt version if quality degrades

---

### 9. Observability (if applicable)

**Metrics Added:**
- `a2_synthesis_total`: counter of synthesis calls (labels: status=success/error)
- `a2_synthesis_latency_seconds`: histogram of synthesis latency
- `a2_sections_produced_total`: histogram of section count per synthesis
- `a2_provenance_valid_total`: counter of provenance validation results (valid/invalid)
- `a2_mermaid_valid_total`: counter of Mermaid syntax validation results
- `a2_katex_valid_total`: counter of KaTeX render validation results

**Tracing/Logging:**
- Span: `a2.synthesize` with attributes (session_id, num_utterances, num_sections, latency_ms)
- Log: INFO on synthesis completion with section count and provenance stats
- Log: WARNING on provenance validation failures
- Log: ERROR on malformed LLM output or context overflow

**Alerts:**
- Provenance validation failure rate > 5%: LLM output quality issue
- Synthesis latency P95 > 60s: LLM serving issue, check S36
- Section count < 1 for non-empty sessions: synthesis quality issue

---

### 10. Exit Checklist

- [ ] All tests pass (T44.1–T44.8)
- [ ] Notes are coherent, provenance-linked, and human-rated at target quality
- [ ] Every section has at least one valid source utterance ID
- [ ] No discarded utterance content appears in notes
- [ ] Mermaid/KaTeX preferred over image requests
- [ ] Full-context approach justified by head-to-head comparison
