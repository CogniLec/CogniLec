# S43 — A1 Ensemble Voting
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** For utterances where the outlier score is ambiguous (~15%), run 2–3 models independently and vote — split votes result in retention plus a review flag, honouring the asymmetric cost design.

**Component Boundaries:**
- **Allowed:** `src/services/agents/a1/ensemble/`, `config/prompts/a1_ensemble/`, `tests/test_a1_ensemble.py`
- **Off-limits:** A1 evaluation (S42), note synthesis (S44), LLM serving (S36)

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| Local LLM | Tier 1 (S36) | Primary inference model |
| LiteLLM | via S37 | Multi-model routing |
| Pydantic | 2.x | Schema definitions |
| pytest | 8.x | Integration tests |

---

### 2. State Machine & Domain Schemas

**Ensemble Voting Flow:**
```
utterance_with_outlier_score
  → check ambiguity band
      ├─ clear_KEEP (score > keep_threshold)    → KEEP directly
      ├─ clear_DISCARD (score < discard_threshold) → DISCARD directly
      └─ ambiguous (within band) → run N models independently
          → collect votes
          → UNANIMOUS_KEEP   → KEEP
          → UNANIMOUS_DISCARD → DISCARD (only if all agree)
          → SPLIT VOTE       → KEEP + flag_for_review
```

**Ambiguity Band:**
```
                    keep_threshold              discard_threshold
                         ↓                            ↓
|------------------------|-------- AMBIGUOUS --------|------------------------|
CLEAR KEEP                                            CLEAR DISCARD
```

**Asymmetric Cost Enforcement:**
- Split vote → KEEP (never discard on disagreement)
- This ensures the asymmetric cost is honoured at the voting level
- Flag for human review to catch systematic errors

**Voting Output Schema:**
```python
# src/services/agents/a1/ensemble/models.py
from pydantic import BaseModel, Field
from enum import Enum


class VoteDecision(str, Enum):
    KEEP = "keep"
    DISCARD = "discard"
    SPLIT_KEEP = "split_keep"  # split vote → retained with flag


class ModelVote(BaseModel):
    model_name: str
    decision: str  # "keep" or "discard"
    confidence: float = Field(..., ge=0.0, le=1.0)
    filter_reason: str


class EnsembleResult(BaseModel):
    utterance_id: str
    final_decision: VoteDecision
    votes: list[ModelVote] = Field(..., min_length=1)
    flagged_for_review: bool = False
    confidence: float = Field(..., ge=0.0, le=1.0)
    model: str  # primary model or "ensemble"


class EnsembleBatchResult(BaseModel):
    session_id: str
    results: list[EnsembleResult]
    single_model_count: int
    ensemble_count: int
    flagged_count: int
```

**State Transition Rules:**
- Utterance enters ensemble with `is_relevant=NULL` (unclassified)
- Clear-KEEP/CLEAR-DISCARD utterances are classified by single model (no ensemble)
- Ambiguous utterances trigger ensemble voting across N models
- Split vote → `is_relevant=true` + `needs_review=true` flag
- All votes stored for audit trail

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Define ensemble output schemas in `src/services/agents/a1/ensemble/models.py` | Schema imports, validates |
| 2 | Implement ambiguity band configuration with thresholds | Config loads, thresholds validated |
| 3 | Implement `EnsembleVoter` class with multi-model voting | Unit test: mock models return votes |
| 4 | Implement single-model path for clear-KEEP/CLEAR-DISCARD | Unit test: clear utterances skip ensemble |
| 5 | Implement split-vote logic: KEEP + flag_for_review | T43.2 passes |
| 6 | Implement configurable ambiguity band | T43.3 passes |
| 7 | Verify model independence (no shared context) | T43.4 passes |
| 8 | Run performance benchmark | T43.5 passes |
| 9 | Verify ensemble improves over single-model baseline | T43.1 passes |

**Atomic Sub-tasks:**
1. Ambiguity band configuration (keep_threshold, discard_threshold)
2. `EnsembleVoter` with multi-model independent voting
3. Single-model path for clear cases
4. Split-vote → KEEP + flag_for_review logic
5. Model independence enforcement (no cross-model context)
6. Performance benchmark within NFR-P3 budget

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| One model fails mid-vote | Use remaining model votes; log warning |
| All models fail | Keep utterance, flag for review, alert |
| Ambiguity band set to zero | Degenerates to single-model (no ensemble) |
| Model disagrees on same utterance across runs | Log instability, flag for review |
| Ensemble exceeds latency budget | Reduce to 2 models, log warning |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Strategy pattern: single-model vs. ensemble paths
- Fan-out pattern: parallel model calls for ensemble
- Guard pattern: ambiguity band as routing guard

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase (`EnsembleVoter`, `EnsembleResult`)
- Files: snake_case (`ensemble_voter.py`, `models.py`)
- Functions: snake_case (`vote_batch`, `classify_ambiguity`)
- Constants: UPPER_SNAKE_CASE (`AMBIGUOUS_BAND_LOW`, `AMBIGUOUS_BAND_HIGH`)

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

**Ensemble Voter Interface:**
```python
# src/services/agents/a1/ensemble/voter.py
class EnsembleVoter:
    def __init__(
        self,
        models: list[str],  # ["tier_1", "tier_2", "tier_3"]
        ambiguity_band: tuple[float, float],  # (low, high) thresholds
        llm_router,  # from S37
    ): ...

    async def vote_batch(
        self,
        utterances: list[Utterance],
        topic_description: str,
    ) -> EnsembleBatchResult:
        """Classify utterances, using ensemble for ambiguous cases."""
        ...

    def _is_ambiguous(self, outlier_score: float) -> bool:
        """Check if outlier score falls within ambiguity band."""
        ...

    async def _single_model_classify(
        self,
        utterance: Utterance,
        topic_description: str,
    ) -> ModelVote:
        """Classify with primary model only."""
        ...

    async def _ensemble_classify(
        self,
        utterance: Utterance,
        topic_description: str,
    ) -> EnsembleResult:
        """Classify with N models independently, vote."""
        ...

    def _resolve_votes(self, votes: list[ModelVote]) -> EnsembleResult:
        """Resolve votes: unanimous → decision, split → KEEP + flag."""
        ...
```

**Ambiguity Band Configuration:**
```python
# config/evaluation/ambiguity_band.yaml
ambiguity_band:
  enabled: true
  keep_threshold: 0.75       # outlier_score > this → clear KEEP
  discard_threshold: 0.25    # outlier_score < this → clear DISCARD
  # Between 0.25 and 0.75 → ambiguous → ensemble voting
  models:
    - tier_1                  # primary local model
    - tier_2                  # secondary model (if available)
  require_unanimous_discard: true  # all models must agree to discard
  flag_on_split: true        # split vote → flag for review
```

**Model Independence Enforcement:**
```python
# src/services/agents/a1/ensemble/voter.py
async def _ensemble_classify(
    self,
    utterance: Utterance,
    topic_description: str,
) -> EnsembleResult:
    """Each model runs independently — no model sees another's output."""
    tasks = []
    for model in self.models:
        # Each model gets the SAME prompt, independently
        task = self._single_model_classify(
            utterance=utterance,
            topic_description=topic_description,
            model_override=model,
        )
        tasks.append(task)

    # Run in parallel, independently
    votes = await asyncio.gather(*tasks)
    return self._resolve_votes(votes)
```

**Vote Resolution Logic:**
```python
def _resolve_votes(self, votes: list[ModelVote]) -> EnsembleResult:
    """Resolve votes with asymmetric cost enforcement."""
    keep_votes = sum(1 for v in votes if v.decision == "keep")
    discard_votes = sum(1 for v in votes if v.decision == "discard")

    # All agree KEEP → KEEP
    if keep_votes == len(votes):
        return EnsembleResult(
            final_decision=VoteDecision.KEEP,
            votes=votes,
            flagged_for_review=False,
            confidence=max(v.confidence for v in votes),
            model="ensemble",
        )

    # All agree DISCARD → DISCARD (only unanimous)
    if discard_votes == len(votes) and self.require_unanimous_discard:
        return EnsembleResult(
            final_decision=VoteDecision.DISCARD,
            votes=votes,
            flagged_for_review=False,
            confidence=max(v.confidence for v in votes),
            model="ensemble",
        )

    # Split vote → KEEP + flag (asymmetric cost)
    return EnsembleResult(
        final_decision=VoteDecision.SPLIT_KEEP,
        votes=votes,
        flagged_for_review=True,
        confidence=min(v.confidence for v in votes),
        model="ensemble",
    )
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Default |
|----------|------|-------------|---------|
| `ENSEMBLE_ENABLED` | bool | Enable ensemble voting | `true` |
| `ENSEMBLE_AMBIGUOUS_LOW` | float | Low threshold for ambiguity band | `0.25` |
| `ENSEMBLE_AMBIGUOUS_HIGH` | float | High threshold for ambiguity band | `0.75` |
| `ENSEMBLE_MODELS` | string | Comma-separated model list | `tier_1,tier_2` |
| `ENSEMBLE_UNANIMOUS_DISCARD` | bool | Require all models to discard | `true` |
| `ENSEMBLE_FLAG_ON_SPLIT` | bool | Flag for review on split vote | `true` |

**Third-Party Integration Contracts:**
- LLM Router (S37): multi-model routing with failover
- Local LLM (S36): Tier 1 model serving

**Version Pins:**
- LiteLLM pinned in `pyproject.toml`
- Model versions pinned in `config/models.yaml`

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T43.1 | V | `pytest tests/test_a1_ensemble.py::test_ensemble_improves_precision -v` | Ensemble discard precision > single-model (S42) baseline |
| T43.2 | I | `pytest tests/test_a1_ensemble.py::test_split_vote_retains -v` | Split vote results in retention + review flag, never discard |
| T43.3 | I | `pytest tests/test_a1_ensemble.py::test_ambiguity_band_configurable -v` | Band thresholds configurable; zero band degenerates to single-model |
| T43.4 | I | `pytest tests/test_a1_ensemble.py::test_models_vote_independently -v` | No model sees another model's output during voting |
| T43.5 | P | `pytest tests/test_a1_ensemble.py::test_ensemble_within_budget -v` | Ensemble stays within NFR-P3 processing budget |

**Test Case Details (Given/When/Then):**

**T43.1 — Ensemble improves discard precision over single-model**
- **Given:** 200 ambiguous utterances from the evaluation set
- **When:** classified by single-model (S42 baseline) and ensemble (2–3 models)
- **Then:** ensemble precision on discard is > single-model precision

**T43.2 — Split vote results in retention plus review flag**
- **Given:** an utterance where model 1 says KEEP and model 2 says DISCARD
- **When:** `EnsembleVoter._resolve_votes()` processes the votes
- **Then:** final decision is `SPLIT_KEEP`, `flagged_for_review=true`, and `is_relevant` is written as `true` (never discard on split)

**T43.3 — Ambiguity band is configurable**
- **Given:** ambiguity band set to (0.25, 0.75) then (0.0, 1.0) then (0.5, 0.5)
- **When:** utterances are classified with each band configuration
- **Then:** with (0.25, 0.75), ambiguous utterances trigger ensemble; with (0.5, 0.5), all utterances use single-model; with (0.0, 1.0), all utterances trigger ensemble

**T43.4 — Models vote independently**
- **Given:** 3 models configured for ensemble voting
- **When:** `_ensemble_classify()` is called for an utterance
- **Then:** each model receives the same prompt independently; no model's output is visible to other models during voting

**T43.5 — Ensemble stays within processing budget**
- **Given:** 100 ambiguous utterances requiring ensemble voting
- **When:** ensemble voting processes the batch
- **Then:** total processing time is within NFR-P3 budget (per-session processing SLA)

**Verification Commands:**
```bash
# Full local verification
uv run pytest tests/test_a1_ensemble.py -v -k "S43 or a1_ensemble" && \
uv run mypy --strict src/services/agents/a1/ensemble/ && \
uv run ruff check src/services/agents/a1/ensemble/
```

**Exit Criteria:**
- [ ] T43.1 passes — ensemble improves discard precision over single-model baseline
- [ ] T43.2 passes — split vote retains, never discards, and flags for review
- [ ] T43.3 passes — ambiguity band is configurable; zero degenerates to single-model
- [ ] T43.4 passes — models vote independently with no cross-model context
- [ ] T43.5 passes — ensemble stays within NFR-P3 processing budget

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- Split vote must always result in KEEP — this is the asymmetric cost enforcement at the voting level
- Model independence is critical: if models share context, they will converge and ensemble provides no benefit
- Ambiguity band width directly affects ensemble cost — wider band = more ensemble calls = higher latency
- `require_unanimous_discard=true` means even 2/3 agreement to discard is split → KEEP
- Ensemble adds latency proportional to number of models — budget-aware model selection

**Fallback Instructions:**
- If ensemble exceeds latency budget: reduce to 2 models, widen clear-KEEP/CLEAR-DISCARD bands
- If ensemble does not improve over single-model: widen ambiguity band, review model diversity
- If one model fails during ensemble: use remaining votes, log warning, flag for review

**Rollback Procedure:**
- Set `ENSEMBLE_ENABLED=false` to disable ensemble entirely (single-model only)
- Set ambiguity band to (0.5, 0.5) to route all utterances through single-model path
- No database changes — ensemble only affects classification routing

---

### 9. Observability (if applicable)

**Metrics Added:**
- `a1_ensemble_total`: counter of ensemble votes (labels: decision=keep/discard/split_keep)
- `a1_ensemble_latency_seconds`: histogram of ensemble voting latency
- `a1_ensemble_single_model_count`: counter of single-model classifications
- `a1_ensemble_ambiguous_count`: counter of ambiguous utterances triggering ensemble
- `a1_ensemble_flagged_total`: counter of utterances flagged for review
- `a1_ensemble_agreement_rate`: gauge of model agreement rate

**Tracing/Logging:**
- Span: `a1.ensemble.classify` with attributes (num_models, is_ambiguous, decision, latency_ms)
- Span: `a1.ensemble.vote` with attributes (utterance_id, votes, decision)
- Log: INFO on ensemble batch completion with single/ensemble/flagged counts
- Log: WARNING on split vote with vote details
- Log: ERROR on model failure during ensemble

**Alerts:**
- Split vote rate > 20%: model disagreement too high, review ambiguity band thresholds
- Ensemble latency P95 > NFR-P3 budget: reduce model count or widen clear bands
- Flagged utterance review backlog > 100: human review process bottleneck

---

### 10. Exit Checklist

- [ ] All tests pass (T43.1, T43.2, T43.3, T43.4, T43.5)
- [ ] Split vote always results in KEEP + review flag (asymmetric cost honoured)
- [ ] Ambiguity band is configurable and documented
- [ ] Models vote independently with no cross-model context
- [ ] Ensemble stays within NFR-P3 processing budget
- [ ] Ensemble measurably improves filtering on ambiguous cases
