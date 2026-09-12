# S42 — A1 Evaluation & Threshold Calibration (HARD GATE)
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Evaluate A1 against 2,000 hand-labelled utterances, tune for high precision on the discard decision, and calibrate thresholds — blocking downstream work until precision on discard > 0.90, recall on off-topic > 0.80, and zero core-content utterances are discarded.

**CRITICAL: This is a HARD GATE.** S41 must pass before evaluation begins. S43, S44, S45, S46 cannot begin until S42 gate criteria pass. Attempting to parallelise past this gate is the primary way this project fails.

**Component Boundaries:**
- **Allowed:** `tests/test_a1_evaluation.py`, `src/services/agents/a1/evaluation/`, `config/evaluation/`, `reports/a1_evaluation/`
- **Off-limits:** A1 filter agent (S41), ensemble voting (S43), note synthesis (S44)

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| scikit-learn | 1.x | Precision, recall, confusion matrix |
| pandas | 2.x | Data manipulation for evaluation set |
| pytest | 8.x | Integration tests |
| promptfoo | 0.x | Prompt regression baseline |

---

### 2. State Machine & Domain Schemas

**Evaluation Gate Flow:**
```
hand_labelled_set (2000 utterances)
  → run A1 on all → collect predictions
  → compute precision/recall per category
  → GATE CHECK:
      ├─ precision on discard > 0.90  → PASS
      ├─ recall on off-topic > 0.80   → PASS
      ├─ zero core-content discarded  → PASS
      └─ ANY FAIL → BLOCK, do not proceed
  → threshold calibration (optimize for asymmetric cost)
  → per-category error analysis
  → evaluation report
```

**Asymmetric-Cost Design (§12.4):**
```
Cost Matrix:
                    Actual KEEP    Actual DISCARD
Predicted KEEP      ✓ correct      ✗ noisy notes (LOW cost)
Predicted DISCARD   ✗ silent loss  ✓ correct (HIGH value)

- Wrongly keeping chatter → slightly noisy notes (detectable, tolerable)
- Wrongly discarding key explanation → silently incomplete notes (UNACCEPTABLE)
- Therefore: tune for HIGH PRECISION on discard, accept lower recall
```

**Evaluation Output Schema:**
```python
# src/services/agents/a1/evaluation/models.py
from pydantic import BaseModel, Field
from enum import Enum

class EvaluationCategory(str, Enum):
    STUDENT_QUESTION = "student_question"
    ADMIN = "admin"
    ASIDE = "aside"
    TANGENT = "tangent"
    CORE_CONTENT = "core_content"

class EvaluationResult(BaseModel):
    category: EvaluationCategory
    utterance_id: str
    ground_truth: bool  # true = relevant, false = off-topic
    predicted: bool
    confidence: float

class EvaluationReport(BaseModel):
    total_utterances: int
    precision_on_discard: float = Field(..., ge=0.0, le=1.0)
    recall_on_offtopic: float = Field(..., ge=0.0, le=1.0)
    core_content_discarded: int = Field(..., ge=0)
    gate_passed: bool
    per_category: dict[str, dict[str, float]]  # category → {precision, recall, f1, support}
    confusion_matrix: dict[str, int]  # TP, FP, TN, FN
    calibrated_threshold: float = Field(..., ge=0.0, le=1.0)
    outlier_score_ablation: dict[str, float] | None = None
```

**State Transition Rules:**
- Evaluation is a point-in-time check, not a persistent state
- Gate passes only if ALL three criteria are met simultaneously
- Threshold calibration produces a single float used by S43 ensemble voting
- Evaluation report persisted for audit trail

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Load 2,000 hand-labelled utterances from `config/evaluation/hand_labelled.csv` | File loads, 2000 rows, no nulls in label column |
| 2 | Run A1 filter on all 2,000 utterances using production prompt and model | All utterances classified |
| 3 | Compute precision on discard, recall on off-topic | Metrics computed, within range |
| 4 | Check gate: precision > 0.90 AND recall > 0.80 AND zero core-content discarded | Gate passes or fails with error report |
| 5 | Perform per-category error analysis | Error rates by category documented |
| 6 | Run outlier score ablation (with vs. without outlier score feature) | Ablation shows outlier score helps |
| 7 | Calibrate threshold for asymmetric cost | Threshold optimized for high discard precision |
| 8 | Generate evaluation report in `reports/a1_evaluation/` | Report saved, gate status recorded |

**Atomic Sub-tasks:**
1. Evaluation data loader (2,000 hand-labelled utterances)
2. A1 batch inference runner
3. Metric computation (precision, recall, confusion matrix)
4. Gate check logic (three-criteria assertion)
5. Per-category error analysis
6. Outlier score ablation study
7. Threshold calibration for asymmetric cost
8. Evaluation report generation and persistence

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| Hand-labelled data has missing labels | Exclude utterances with null labels; log warning; report coverage |
| A1 fails to classify some utterances | Report classification rate; gate requires > 99% classification |
| Precision on discard < 0.90 | **GATE FAILS.** Do not proceed. Tune prompt/threshold and re-evaluate |
| Recall on off-topic < 0.80 | **GATE FAILS.** Do not proceed. Investigate false negatives |
| Any core-content utterance discarded | **GATE FAILS IMMEDIATELY.** Unacceptable failure — this is the hard assertion |
| All utterances classified as KEEP | Gate fails (recall = 0); investigate model or prompt |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Pipeline pattern: data → inference → metrics → gate → report
- Evaluation runner: `A1EvaluationRunner` orchestrates the full evaluation
- Reporter pattern: `EvaluationReport` generated and persisted

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase (`A1EvaluationRunner`, `EvaluationReport`)
- Files: snake_case (`evaluation_runner.py`, `hand_labelled.csv`)
- Functions: snake_case (`compute_metrics`, `calibrate_threshold`)
- Constants: UPPER_SNAKE_CASE (`DISCARD_PRECISION_THRESHOLD`, `OFFTOPIC_RECALL_THRESHOLD`)

**Code Splitting Metrics:**
- Max function length: 40 lines
- Max file length: 400 lines
- Evaluation scripts may be longer but should be decomposed

**Type Safety:**
- All function signatures typed with Pydantic v2 models
- `from __future__ import annotations` in all files
- Evaluation results are Pydantic models, not raw dicts

---

### 5. API & Interface Contracts

**Evaluation Runner Interface:**
```python
# src/services/agents/a1/evaluation/runner.py
class A1EvaluationRunner:
    def __init__(
        self,
        a1_agent: A1FilterAgent,
        labelled_data_path: Path,
    ):
        ...

    async def run_evaluation(self) -> EvaluationReport:
        """Run full evaluation against hand-labelled set.

        Returns EvaluationReport with gate status.
        Raises EvaluationGateFailure if gate criteria not met.
        """
        ...

    def _check_gate(self, report: EvaluationReport) -> bool:
        """Check if all gate criteria pass.

        Gate criteria (ALL must pass):
        1. precision_on_discard > 0.90
        2. recall_on_offtopic > 0.80
        3. core_content_discarded == 0
        """
        ...

    def _compute_per_category(
        self, results: list[EvaluationResult]
    ) -> dict[str, dict[str, float]]:
        """Compute precision, recall, f1 per category."""
        ...

    def _calibrate_threshold(
        self, results: list[EvaluationResult]
    ) -> float:
        """Find threshold that maximizes precision while maintaining recall > 0.80."""
        ...
```

**Hand-Labelled Data Format (`config/evaluation/hand_labelled.csv`):**
```csv
utterance_id,session_id,text,speaker_tag,outlier_score,ground_truth_label,category
uuid-001,uuid-s001,"Can you explain eigenvalues?",student,0.12,TRUE,student_question
uuid-002,uuid-s001,"Let me check the weather",lecturer,0.87,FALSE,aside
uuid-003,uuid-s001,"The derivative of sin is cos",lecturer,0.05,TRUE,core_content
```

**Evaluation Report Output (`reports/a1_evaluation/eval_report.json`):**
```json
{
  "total_utterances": 2000,
  "precision_on_discard": 0.93,
  "recall_on_offtopic": 0.84,
  "core_content_discarded": 0,
  "gate_passed": true,
  "per_category": {
    "student_question": {"precision": 0.96, "recall": 0.92, "f1": 0.94, "support": 380},
    "admin": {"precision": 0.88, "recall": 0.78, "f1": 0.83, "support": 120},
    "aside": {"precision": 0.91, "recall": 0.85, "f1": 0.88, "support": 250},
    "tangent": {"precision": 0.89, "recall": 0.82, "f1": 0.85, "support": 200},
    "core_content": {"precision": 1.00, "recall": 1.00, "f1": 1.00, "support": 1050}
  },
  "confusion_matrix": {"TP": 1680, "FP": 105, "TN": 210, "FN": 5},
  "calibrated_threshold": 0.72,
  "outlier_score_ablation": {
    "with_outlier": {"precision": 0.93, "recall": 0.84},
    "without_outlier": {"precision": 0.89, "recall": 0.81}
  }
}
```

**Gate Assertion Interface:**
```python
# src/services/agents/a1/evaluation/gate.py
DISCARD_PRECISION_THRESHOLD = 0.90
OFFTOPIC_RECALL_THRESHOLD = 0.80

class EvaluationGateFailure(Exception):
    def __init__(self, report: EvaluationReport, failures: list[str]):
        self.report = report
        self.failures = failures
        msg = f"A1 evaluation gate FAILED: {'; '.join(failures)}"
        super().__init__(msg)

def assert_gate_passes(report: EvaluationReport) -> None:
    """Assert all gate criteria. Raises EvaluationGateFailure on failure."""
    failures = []
    if report.precision_on_discard < DISCARD_PRECISION_THRESHOLD:
        failures.append(f"precision on discard {report.precision_on_discard:.3f} < {DISCARD_PRECISION_THRESHOLD}")
    if report.recall_on_offtopic < OFFTOPIC_RECALL_THRESHOLD:
        failures.append(f"recall on off-topic {report.recall_on_offtopic:.3f} < {OFFTOPIC_RECALL_THRESHOLD}")
    if report.core_content_discarded > 0:
        failures.append(f"{report.core_content_discarded} core-content utterances discarded (must be 0)")
    if failures:
        raise EvaluationGateFailure(report, failures)
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Default |
|----------|------|-------------|---------|
| `A1_EVAL_DATA_PATH` | string | Path to hand-labelled CSV | `config/evaluation/hand_labelled.csv` |
| `A1_EVAL_REPORT_DIR` | string | Directory for evaluation reports | `reports/a1_evaluation/` |
| `DISCARD_PRECISION_THRESHOLD` | float | Minimum precision on discard | `0.90` |
| `OFFTOPIC_RECALL_THRESHOLD` | float | Minimum recall on off-topic | `0.80` |
| `A1_EVAL_MAXConcurrency` | int | Max concurrent LLM calls during eval | `4` |

**Third-Party Integration Contracts:**
- scikit-learn: precision_score, recall_score, confusion_matrix, classification_report
- pandas: CSV loading and data manipulation
- A1 filter agent (S41): `classify_batch()` must be functional

**Version Pins:**
- scikit-learn pinned in `pyproject.toml`
- pandas pinned in `pyproject.toml`

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T42.1 | V | `pytest tests/test_a1_evaluation.py::test_gate_precision_on_discard -v` | **GATE:** precision on discard > 0.90 |
| T42.2 | V | `pytest tests/test_a1_evaluation.py::test_gate_recall_on_offtopic -v` | **GATE:** recall on off-topic > 0.80 |
| T42.3 | V | `pytest tests/test_a1_evaluation.py::test_per_category_error_analysis -v` | Error analysis covers all 5 categories |
| T42.4 | V | `pytest tests/test_a1_evaluation.py::test_zero_core_content_discarded -v` | **GATE:** zero core-content utterances discarded |
| T42.5 | V | `pytest tests/test_a1_evaluation.py::test_outlier_score_ablation -v` | Outlier score confirmed as informative feature |

**Test Case Details (Given/When/Then):**

**T42.1 — GATE: precision on discard > 0.90**
- **Given:** 2,000 hand-labelled utterances with ground truth labels
- **When:** A1 classifies all utterances and predictions are compared to ground truth
- **Then:** precision on the discard decision (TP / (TP + FP) where positive = discard) > 0.90

**T42.2 — GATE: recall on off-topic > 0.80**
- **Given:** 2,000 hand-labelled utterances with ground truth labels
- **When:** A1 classifies all utterances and predictions are compared to ground truth
- **Then:** recall on off-topic detection (TP / (TP + FN) where positive = off-topic) > 0.80

**T42.3 — Error analysis by utterance category**
- **Given:** 2,000 hand-labelled utterances across 5 categories (student_question, admin, aside, tangent, core_content)
- **When:** per-category metrics are computed
- **Then:** precision, recall, f1, and support are reported for each category

**T42.4 — Zero core-content utterances discarded**
- **Given:** 2,000 hand-labelled utterances including core_content category
- **When:** A1 classifications are checked against core_content ground truth
- **Then:** zero utterances in the core_content category have `is_relevant=false` (this is the unacceptable failure)

**T42.5 — Outlier score confirmed as informative**
- **Given:** 2,000 hand-labelled utterances with outlier scores
- **When:** A1 runs twice — once with outlier scores in prompt, once without
- **Then:** with-outlier precision and recall are both >= without-outlier metrics (ablation confirms feature helps)

**Verification Commands:**
```bash
# Full local verification (requires hand-labelled data)
uv run pytest tests/test_a1_evaluation.py -v -k "S42 or a1_evaluation" && \
uv run mypy --strict src/services/agents/a1/evaluation/ && \
uv run ruff check src/services/agents/a1/evaluation/

# Generate evaluation report
uv run python -m src.services.agents.a1.evaluation.runner
```

**Exit Criteria:**
- [ ] **T42.1 GATE PASSES** — precision on discard > 0.90
- [ ] **T42.2 GATE PASSES** — recall on off-topic > 0.80
- [ ] T42.3 passes — per-category error analysis complete
- [ ] **T42.4 GATE PASSES** — zero core-content utterances discarded
- [ ] T42.5 passes — outlier score confirmed as informative
- [ ] Evaluation report persisted in `reports/a1_evaluation/`
- [ ] Calibrated threshold documented for S43

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- This is a HARD GATE — if criteria fail, S43–S46 cannot begin. Do not fudge numbers.
- Core-content discard is the zero-tolerance assertion: one discarded core-content utterance means the gate fails
- Precision on discard is asymmetric: we measure precision specifically for the discard class, not overall precision
- Hand-labelled data must be representative — biased labels produce misleading metrics
- Outlier score ablation must show improvement — if not, the feature is noise and should be removed from A1 prompt

**Fallback Instructions:**
- If precision < 0.90: increase confidence threshold, add more KEEP-biased few-shot examples to A1 prompt
- If recall < 0.80: lower confidence threshold, add more DISCARD-biased few-shot examples
- If core-content discarded > 0: **STOP.** Investigate which utterances were misclassified and why. Fix A1 prompt before re-evaluating
- If outlier ablation shows no improvement: remove outlier score from A1 prompt (simpler prompt)

**Rollback Procedure:**
- Evaluation is read-only against hand-labelled data — no production changes to rollback
- If gate fails, A1 filter (S41) prompt or threshold must be adjusted before re-running evaluation
- Hand-labelled data is versioned in `config/evaluation/` — track which version was used for each evaluation run

---

### 9. Observability (if applicable)

**Metrics Added:**
- `a1_eval_gate_passed`: gauge (1 = passed, 0 = failed)
- `a1_eval_precision_on_discard`: gauge
- `a1_eval_recall_on_offtopic`: gauge
- `a1_eval_core_content_discarded`: gauge (must be 0)
- `a1_eval_total_utterances`: gauge
- `a1_eval_duration_seconds`: gauge

**Tracing/Logging:**
- Span: `a1.evaluation.run` with attributes (total_utterances, gate_passed, latency_ms)
- Log: INFO on evaluation completion with metrics summary
- Log: ERROR on gate failure with detailed breakdown
- Log: INFO on threshold calibration result

**Alerts:**
- Gate failure: **CRITICAL** — blocks all downstream stages (S43–S46)
- Core-content discard > 0: **CRITICAL** — investigate immediately
- Precision drop from previous evaluation: investigate prompt drift

---

### 10. Exit Checklist

- [ ] **T42.1 GATE PASSES** — precision on discard > 0.90
- [ ] **T42.2 GATE PASSES** — recall on off-topic > 0.80
- [ ] **T42.4 GATE PASSES** — zero core-content utterances discarded
- [ ] T42.3 passes — per-category error analysis complete
- [ ] T42.5 passes — outlier score ablation confirms feature helps
- [ ] Evaluation report saved to `reports/a1_evaluation/`
- [ ] Calibrated threshold documented for S43 ensemble voting
- [ ] All gate criteria met simultaneously — S43 is unblocked
