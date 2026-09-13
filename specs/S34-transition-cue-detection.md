# S34 — Transition Cue Detection
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Implement a curated high-precision pattern set for explicit forward references ("next we'll cover", "moving on to", "that completes", "before the break") plus LLM confirmation of candidates, where cues boost boundary scores in S28 rather than overriding them — a second independent signal for segmentation.

**Component Boundaries:**
- **Allowed:** `src/ml/transition_cues/`, `src/services/transition_cues.py`, `tests/test_transition_cues.py`, `config/transition_patterns.yaml`
- **Off-limits:** Segmentation algorithm (S28), topic labelling (S31), clustering (S30), session type classification (S35)

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| regex | 2024.x | Pattern matching for transition cues |
| LLM (local vLLM) | 0.5.x | Candidate confirmation step |
| pydantic | 2.x | Config and result models |
| pytest | 8.x | Unit and integration tests |

---

### 2. State Machine & Domain Schemas

**Transition Cue Detection Pipeline:**
```
Input: session utterances with timestamps
  ↓
Scan all utterances for transition cue patterns (high-precision regex)
  ↓
Collect candidate cue positions
  ↓
LLM confirms each candidate (contextual validation)
  ↓
Confirmed cues → boundary score boost values
  ↓
Boost scores added to S28 boundary scores (additive, not overriding)
  ↓
Output: list of TransitionCue (position, pattern, confidence, boost_value)
```

**Cue Categories:**
```
FORWARD_REFERENCE:
  "next we'll cover", "moving on to", "let's talk about"
  "after the break we'll", "coming up next"

COMPLETION_SIGNAL:
  "that completes", "that wraps up", "so to summarize"
  "in conclusion", "that's all for"

TRANSITION_MARKER:
  "before the break", "first let's", "now let's turn to"
  "the next topic is", "switching gears to"
```

**Pydantic Models:**
```python
# src/ml/transition_cues/models.py
from pydantic import BaseModel, Field
from enum import Enum


class CueCategory(str, Enum):
    FORWARD_REFERENCE = "forward_reference"
    COMPLETION_SIGNAL = "completion_signal"
    TRANSITION_MARKER = "transition_marker"


class TransitionPattern(BaseModel):
    pattern: str  # Regex pattern
    category: CueCategory
    boost_value: float = Field(
        default=0.15, ge=0.0, le=0.5, description="Additive boost to boundary score"
    )
    confidence_base: float = Field(
        default=0.7, ge=0.0, le=1.0, description="Base confidence before LLM confirmation"
    )
    language: str = "en"


class TransitionCueConfig(BaseModel):
    patterns_file: str = "config/transition_patterns.yaml"
    llm_confirmation_model: str = "phi-3-mini-3.8b-4bit"
    llm_confirmation_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    max_boost_per_cue: float = Field(default=0.3, ge=0.0, le=1.0)
    context_window_utterances: int = Field(
        default=5, ge=1, le=10, description="Context around cue for LLM confirmation"
    )
    enabled: bool = True


class TransitionCue(BaseModel):
    position: int  # Utterance index where cue was detected
    pattern_matched: str
    category: CueCategory
    confidence: float
    boost_value: float
    llm_confirmed: bool
    llm_confidence: float | None = None
    context_before: str | None = None
    context_after: str | None = None


class TransitionCueResult(BaseModel):
    session_id: str
    cues: list[TransitionCue]
    total_boost: float  # Sum of all boost values
    patterns_matched: int
    llm_confirmed_count: int
```

**Boundary Score Boost Logic:**
```
For each detected cue at position P:
  1. Get S28 boundary score at position P (depth_score)
  2. If cue is LLM-confirmed: boost = min(cue.boost_value, max_boost_per_cue)
  3. If cue is not LLM-confirmed: boost = 0 (rejected)
  4. New boundary score = original_score + boost
  5. Re-evaluate boundary detection threshold against boosted scores
```

**State Transition Rules:**
- Cue detection runs after S28 segmentation produces initial boundary scores
- Detected cues boost scores; they do NOT create new boundaries independently
- If a cue boosts a score above the adaptive threshold, it becomes a boundary
- If a cue boosts an already-boundary position, it increases confidence
- Cues in the middle of a coherent topic do NOT force splits — they boost, not override

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Create `config/transition_patterns.yaml` with categorized patterns | YAML loads without error, patterns cover all categories |
| 2 | Implement regex-based pattern matching across utterances | T34.1: patterns match intended phrasings |
| 3 | Implement LLM confirmation step with context window | LLM confirms true transitions, rejects false positives |
| 4 | Implement boundary score boost integration with S28 | Boost values added correctly to existing scores |
| 5 | Run precision evaluation on S05 corpus | T34.2: precision > 0.85 |
| 6 | Run P_k comparison with/without cues | T34.3: P_k improves vs S29 baseline |
| 7 | Test spurious split prevention | T34.4: cue in coherent topic does not force split |

**Atomic Sub-tasks:**
1. Transition pattern configuration and loader
2. Regex-based cue detection across utterances
3. LLM confirmation step with contextual validation
4. Boundary score boost integration with S28 output
5. Precision evaluation against S05 corpus
6. P_k comparison (with/without cues)
7. False positive prevention (coherent topic test)

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| Pattern matches mid-sentence | Only match at utterance start or after sentence boundary (`.`, `?`, `!`) |
| LLM confirmation unavailable | Fall back to base confidence only; cue still boosts if above threshold |
| Multiple cues at same position | Use highest-boost cue; do not double-boost |
| Cue in first/last utterance | Ignore — boundaries at session edges are not meaningful |
| Pattern matches non-transition phrase | LLM confirmation step catches false positives; reject if LLM confidence < threshold |
| All utterances match a pattern | Pattern set too broad; reduce to high-precision patterns only |
| Boost pushes score above threshold at weak boundary | Accept — cue earned its place; evaluate downstream |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Strategy pattern: pluggable pattern sets per language
- Pipeline pattern: sequential pattern match → LLM confirm → boost
- Adapter pattern: wraps S28 boundary scores, adds boost, re-evaluates
- Guard pattern: ensures cues boost, never override

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase
- Files: snake_case (`cue_detector.py`, `llm_confirmer.py`, `score_booster.py`)
- Constants: UPPER_SNAKE_CASE

**Code Splitting Metrics:**
- Max function length: 40 lines
- Max file length: 300 lines

**Type Safety:**
- All function signatures typed with Pydantic v2 models
- `from __future__ import annotations` in all files

---

### 5. API & Interface Contracts

**Transition Cue Detector Interface:**
```python
# src/ml/transition_cues/detector.py
class TransitionCueDetector:
    def __init__(self, config: TransitionCueConfig):
        self.config = config
        self._patterns: list[TransitionPattern] = []
        self._load_patterns()

    def detect(
        self,
        utterances: list[str],
        timestamps: list[float] | None = None,
    ) -> list[TransitionCue]:
        """
        Scan all utterances for transition cue patterns.
        Returns list of detected cues (pre-LLM confirmation).
        """
        candidates = []
        for i, utterance in enumerate(utterances):
            for pattern in self._patterns:
                match = pattern.pattern.search(utterance.lower())
                if match and self._is_valid_position(i, len(utterances)):
                    candidates.append(
                        TransitionCue(
                            position=i,
                            pattern_matched=match.group(),
                            category=pattern.category,
                            confidence=pattern.confidence_base,
                            boost_value=pattern.boost_value,
                            llm_confirmed=False,  # Pending LLM confirmation
                        )
                    )
        return candidates

    def _is_valid_position(self, pos: int, total: int) -> bool:
        """Reject cues at session edges."""
        return 0 < pos < total - 1
```

**LLM Confirmation Interface:**
```python
# src/ml/transition_cues/llm_confirmer.py
class LLMTransitionConfirmer:
    def __init__(self, config: TransitionCueConfig):
        self.config = config
        self.llm_client = None  # Lazy init from S36

    async def confirm_cues(
        self,
        utterances: list[str],
        candidates: list[TransitionCue],
    ) -> list[TransitionCue]:
        """
        Confirm each candidate cue using LLM with context window.
        Returns list of confirmed cues only.
        """
        confirmed = []
        for cue in candidates:
            context = self._extract_context(utterances, cue.position)
            is_valid = await self._llm_confirm(context, cue)
            if is_valid:
                cue.llm_confirmed = True
                cue.confidence = min(1.0, cue.confidence * 1.2)
                confirmed.append(cue)
        return confirmed

    def _extract_context(self, utterances: list[str], position: int) -> str:
        """Extract context window around cue position."""
        start = max(0, position - self.config.context_window_utterances)
        end = min(len(utterances), position + self.config.context_window_utterances + 1)
        return "\n".join(utterances[start:end])

    async def _llm_confirm(self, context: str, cue: TransitionCue) -> bool:
        """Use LLM to confirm if cue represents a real topic transition."""
        prompt = f"""Does the following text contain a clear topic transition or forward reference?
Focus on explicit transition markers, not casual mentions.

Text:
{context}

Answer YES if this is a genuine transition marker, NO if it's incidental.
Answer with confidence score 0.0-1.0 after YES/NO."""

        response = await self.llm_client.complete(prompt)
        return self._parse_confirmation(response)

    def _parse_confirmation(self, response: str) -> bool:
        """Parse LLM response for YES/NO and confidence."""
        lines = response.strip().split("\n")
        decision = lines[0].strip().upper()
        confidence = float(lines[1].strip()) if len(lines) > 1 else 0.5
        return decision.startswith("YES") and confidence >= self.config.llm_confirmation_threshold
```

**Score Booster Interface:**
```python
# src/ml/transition_cues/score_booster.py
class BoundaryScoreBooster:
    def __init__(self, config: TransitionCueConfig):
        self.config = config

    def boost_scores(
        self,
        boundary_scores: list[float],
        cues: list[TransitionCue],
    ) -> list[float]:
        """
        Additively boost boundary scores at cue positions.
        Does NOT create new boundaries — only boosts existing scores.

        IMPORTANT: This is additive, not overriding.
        Cues boost, they do not replace the segmentation algorithm.
        """
        boosted = boundary_scores.copy()
        for cue in cues:
            if cue.llm_confirmed:
                boost = min(cue.boost_value, self.config.max_boost_per_cue)
                if 0 <= cue.position < len(boosted):
                    boosted[cue.position] += boost
        return boosted
```

**Pattern Configuration File:**
```yaml
# config/transition_patterns.yaml
patterns:
  - pattern: "next we(?:'ll| will) (?:cover|discuss|talk about|look at)"
    category: forward_reference
    boost_value: 0.20
    confidence_base: 0.80

  - pattern: "moving on to"
    category: forward_reference
    boost_value: 0.18
    confidence_base: 0.85

  - pattern: "let's (?:now |next )?(?:talk about|discuss|look at|turn to)"
    category: forward_reference
    boost_value: 0.15
    confidence_base: 0.75

  - pattern: "that (?:completes|wraps up|concludes)"
    category: completion_signal
    boost_value: 0.20
    confidence_base: 0.85

  - pattern: "(?:in |to )?summary|so (?:to )?summarize"
    category: completion_signal
    boost_value: 0.18
    confidence_base: 0.80

  - pattern: "that's all for"
    category: completion_signal
    boost_value: 0.22
    confidence_base: 0.90

  - pattern: "before the break"
    category: transition_marker
    boost_value: 0.20
    confidence_base: 0.85

  - pattern: "(?:the )?next topic is"
    category: transition_marker
    boost_value: 0.22
    confidence_base: 0.90

  - pattern: "switching gears to"
    category: transition_marker
    boost_value: 0.15
    confidence_base: 0.80

  - pattern: "now let's (?:turn to|move to|start with)"
    category: transition_marker
    boost_value: 0.18
    confidence_base: 0.82

  - pattern: "coming up (?:next|now|we have)"
    category: forward_reference
    boost_value: 0.16
    confidence_base: 0.78

  - pattern: "after the break (?:we(?:'ll| will)|I(?:'ll| will))"
    category: forward_reference
    boost_value: 0.20
    confidence_base: 0.88
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Default |
|----------|------|-------------|---------|
| `TRANSITION_PATTERNS_FILE` | string | Path to patterns YAML | `config/transition_patterns.yaml` |
| `TRANSITION_LLM_MODEL` | string | Model for LLM confirmation | `phi-3-mini-3.8b-4bit` |
| `TRANSITION_LLM_THRESHOLD` | float | LLM confirmation confidence threshold | `0.6` |
| `TRANSITION_MAX_BOOST` | float | Maximum boost per cue | `0.3` |
| `TRANSITION_CONTEXT_WINDOW` | int | Context utterances for LLM confirmation | `5` |
| `TRANSITION_CUES_ENABLED` | bool | Enable/disable cue detection | `true` |

**Third-Party Integration Contracts:**
- S28 Boundary Detection: receives boundary scores as input, returns boosted scores
- S36 Local LLM Serving: LLM confirmation step uses Tier 1 model
- S29 Segmentation Evaluation: P_k comparison requires S05 corpus access

**Version Pins:**
- regex >= 2024.0 (Unicode support)
- LLM client: OpenAI-compatible API from S36

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T34.1 | U | `pytest tests/test_transition_cues.py::test_patterns_match_intended_phrases -v` | Each pattern matches its intended phrasings |
| T34.2 | V | `pytest tests/test_transition_cues.py::test_precision_on_s05_corpus -v` | Precision > 0.85 on S05 corpus |
| T34.3 | V | `pytest tests/test_transition_cues.py::test_improves_pk -v` | Adding cues improves P_k versus S29 baseline |
| T34.4 | I | `pytest tests/test_transition_cues.py::test_no_spurious_split -v` | Cue in coherent topic does not force spurious split |

**Test Case Details (Given/When/Then):**

**T34.1 — Each pattern matches its intended phrasings**
- **Given:** the pattern set in `config/transition_patterns.yaml` with 12 patterns across 3 categories
- **When:** test utterances containing "Next we'll cover photosynthesis", "Moving on to mitosis", "That completes the first section", "Before the break, let's review" are scanned
- **Then:** each utterance matches its corresponding pattern, with correct category assignment and confidence_base value

**T34.2 — Precision > 0.85 on S05 corpus**
- **Given:** the S05 hand-marked lecture corpus with known transition points
- **When:** transition cue detection (regex + LLM confirmation) is run over all utterances
- **Then:** precision (true positives / (true positives + false positives)) > 0.85; recall may be low (by design — high-precision pattern set)

**T34.3 — Adding cues improves P_k versus S29 baseline**
- **Given:** S05 corpus with S28 segmentation and S29 baseline P_k
- **When:** transition cue boosts are added to S28 boundary scores and segmentation is re-evaluated
- **Then:** P_k with cues < P_k without cues (measurable improvement); WindowDiff also improves

**T34.4 — Cue in coherent topic does not force spurious split**
- **Given:** a session segment where a lecturer says "Moving on to the next example of the same topic" (not a real transition)
- **When:** transition cue detection runs and the cue is evaluated
- **Then:** the cue is detected by regex, but LLM confirmation rejects it (low confidence), so no boost is applied, and no spurious boundary is created

**Verification Commands:**
```bash
uv run pytest tests/test_transition_cues.py -v -k "S34" && \
uv run mypy --strict src/ml/transition_cues/ && \
uv run ruff check src/ml/transition_cues/
```

**Exit Criteria:**
- [ ] T34.1 passes — patterns match intended phrasings
- [ ] T34.2 passes — precision > 0.85 on S05 corpus
- [ ] T34.3 passes — P_k improves vs S29 baseline
- [ ] T34.4 passes — no spurious splits from cues in coherent topics
- [ ] Transition cues measurably improve segmentation without introducing false splits

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- **Cues boost, not override** — the most common mistake is implementing cues as independent boundary creators; they must add to existing S28 scores
- LLM confirmation is the primary false-positive filter; if LLM is unavailable, base confidence must be conservative to avoid precision regression
- Patterns must be high-precision by design; a pattern set that matches too broadly will tank precision and negate the boost benefit
- Regex patterns must be case-insensitive and handle ASR artifacts (e.g., "we'll" might be transcribed as "we will" or "well")
- Boost values must be capped per cue; otherwise a single cue can push a weak boundary above threshold inappropriately
- LLM confirmation context window must be large enough to understand the transition but not so large it dilutes the signal

**Fallback Instructions:**
- If LLM confirmation fails: use base confidence only; cue still boosts if above `llm_confirmation_threshold`
- If patterns file is missing: use built-in default patterns, log warning
- If P_k regresses: disable cues (`TRANSITION_CUES_ENABLED=false`), investigate pattern set
- If precision < 0.85: add more LLM confirmation steps or tighten regex patterns

**Rollback Procedure:**
- Disable transition cues: set `TRANSITION_CUES_ENABLED=false` in env
- Remove boosted scores: re-run S28 segmentation without boost layer
- No database schema changes — cues are computed, not persisted
- Pattern changes are config-only; revert `config/transition_patterns.yaml` to previous version

---

### 9. Observability (if applicable)

**Metrics Added:**
- `transition_cue_detection_total`: counter of cue detection runs
- `transition_cue_candidates_total`: counter of regex matches before LLM confirmation (labels: category)
- `transition_cue_confirmed_total`: counter of LLM-confirmed cues (labels: category)
- `transition_cue_boost_total`: counter of boosts applied to boundary scores
- `transition_cue_precision`: gauge of precision on evaluation corpus
- `transition_cue_pk_delta`: gauge of P_k improvement with vs without cues

**Tracing/Logging:**
- Span: `transition_cue.detect` with attributes (session_id, utterance_count, candidates_found)
- Span: `transition_cue.llm_confirm` with attributes (cue_position, category, llm_confidence, confirmed)
- Span: `transition_cue.boost_scores` with attributes (cues_applied, total_boost)
- Log: INFO on cue detection with pattern and position
- Log: INFO on LLM confirmation with decision and confidence
- Log: WARN on LLM confirmation failure (falling back to base confidence)
- Log: DEBUG on regex matching per utterance

**Alerts:**
- Precision < 0.85 on S05 corpus: pattern set needs tightening
- P_k regression after adding cues: disable cues, investigate
- LLM confirmation failure rate > 20%: check LLM service health
- Boost values exceeding max_boost: cap enforcement bug

---

### 10. Exit Checklist

- [ ] All tests pass (T34.1, T34.2, T34.3, T34.4)
- [ ] Each pattern matches its intended phrasings
- [ ] Precision > 0.85 on S05 corpus (high-precision by design)
- [ ] P_k improves vs S29 baseline (must earn its place)
- [ ] Cues in coherent topics do not force spurious splits
- [ ] LLM confirmation step filters false positives
- [ ] Boundary score boost is additive, not overriding
- [ ] Config file supports categorized patterns per language
- [ ] Rollback via env flag disables cues cleanly
