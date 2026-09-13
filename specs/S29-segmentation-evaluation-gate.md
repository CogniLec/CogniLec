# S29 — Segmentation Evaluation (HARD GATE)
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Evaluate segmentation against the 30 hand-marked lectures from S05 using P_k and WindowDiff, tune the adaptive threshold, and compare against baselines. This is a HARD GATE — clustering (S30) cannot proceed until P_k < 0.30 is achieved.

**Component Boundaries:**
- **Allowed:** `src/eval/segmentation_eval.py`, `src/ml/segmentation/`, `scripts/eval_s29.py`, `tests/test_segmentation_eval.py`
- **Off-limits:** Clustering (S30), topic labelling (S31), cross-session identity (S32)

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| segeval | 0.1.2 | P_k and WindowDiff computation |
| scikit-learn | 1.5.1 | Statistical metrics |
| pandas | 2.2.2 | Results analysis |
| numpy | 1.26.x | Baseline implementations |
| MLflow | 2.16.2 | Evaluation tracking |
| pytest | 8.x | Test runner |

---

### 2. State Machine & Domain Schemas

**Evaluation Pipeline:**
```
Load S05 ground truth → Load segmentation predictions → Compute P_k → Compute WindowDiff
    ↓
Compare against baselines (random, fixed-window, published method)
    ↓
Tune adaptive threshold → Re-evaluate → Check gate
    ↓
Gate pass (P_k < 0.30) → Proceed to S30
Gate fail → Revise segmentation approach, loop back to S28
```

**Pydantic Models:**
```python
# src/eval/segmentation_eval.py
from pydantic import BaseModel, Field


class SegmentationEvalConfig(BaseModel):
    ground_truth_path: str = "lis-eval/labels/v1/boundaries/"
    pk_threshold: float = Field(default=0.30, description="HARD GATE threshold for P_k")
    num_conditions: int = 2  # discussion-heavy vs monologue
    mlflow_experiment: str = "S29_Segmentation_Eval"


class EvalResult(BaseModel):
    session_id: str
    pk: float
    window_diff: float
    num_segments_predicted: int
    num_segments_ground_truth: int
    condition: str  # "discussion_heavy" or "monologue"


class BaselineResult(BaseModel):
    baseline_name: str
    pk: float
    window_diff: float
    description: str


class GateResult(BaseModel):
    gate_passed: bool
    pk_mean: float
    pk_std: float
    window_diff_mean: float
    window_diff_std: float
    baselines: list[BaselineResult]
    beats_baselines: bool
    condition_results: dict[str, dict]  # per-condition breakdown
    recommendation: str
```

**P_k Metric:**
```
P_k = (number of incorrect boundary decisions) / (total number of utterance pairs)
- Compares predicted boundaries against ground truth
- P_k = 0.0 means perfect segmentation
- P_k < 0.30 is the gate threshold
```

**WindowDiff Metric:**
```
WindowDiff = (number of windows with disagreement) / (total windows)
- Sliding window comparison
- More robust to small boundary shifts than P_k
- Recorded alongside P_k for completeness
```

**Baseline Methods:**
```
1. Random: boundaries placed at random positions
2. Fixed-window: segments of fixed size (e.g., every 20 utterances)
3. Published method: TextTiling original (for reference comparison)
```

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Load S05 ground truth boundaries from DVC | 30 lectures loaded |
| 2 | Run segmentation on the same 30 lectures | Predictions generated |
| 3 | Compute P_k and WindowDiff per lecture | Metrics calculated |
| 4 | Implement random baseline | Random P_k > 0.5 typically |
| 5 | Implement fixed-window baseline | Fixed-window P_k recorded |
| 6 | Implement TextTiling original baseline | Reference P_k recorded |
| 7 | Compare segmentation against baselines | T29.3 passes |
| 8 | Tune adaptive threshold | Optimal threshold determined |
| 9 | Report per-condition results | T29.4 passes |
| 10 | Check HARD GATE | T29.1, T29.3 pass |
| 11 | Log to MLflow | Results tracked |

**Atomic Sub-tasks:**
1. Ground truth loading from S05 DVC labels
2. Prediction generation from S28 segmentation
3. P_k computation per lecture
4. WindowDiff computation per lecture
5. Baseline implementations (random, fixed-window, TextTiling)
6. Threshold tuning grid search
7. Per-condition analysis (discussion-heavy vs monologue)
8. MLflow result logging
9. Gate check script

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| S05 labels not available | DVC pull failed; check MinIO connectivity |
| Segmentation produces 0 segments | P_k undefined; assign P_k = 1.0 (worst) |
| Segmentation produces 1 segment per utterance | P_k = 1.0 (worst); over-segmentation |
| Gate P_k fails | STOP — do not proceed to S30; revise segmentation |
| Baseline P_k < segmentation P_k | Baseline is better; investigate |
| Threshold tuning overfits | Use held-out set; report train/test split |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Pipeline pattern: sequential eval stages
- Strategy pattern: pluggable baselines
- Report pattern: structured eval results

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase
- Files: snake_case (`segmentation_eval.py`, `eval_s29.py`)
- Constants: UPPER_SNAKE_CASE

**Code Splitting Metrics:**
- Max function length: 40 lines
- Max file length: 300 lines

**Type Safety:**
- All function signatures typed with Pydantic v2 models
- `from __future__ import annotations` in all files

---

### 5. API & Interface Contracts

**Evaluation Interface:**
```python
# src/eval/segmentation_eval.py
class SegmentationEvaluator:
    def __init__(self, config: SegmentationEvalConfig):
        self.config = config

    def load_ground_truth(self) -> dict[str, list[int]]:
        """Load S05 boundary labels. Returns {session_id: [boundary_positions]}."""

    def compute_pk(
        self,
        ground_truth: list[int],
        predicted: list[int],
        num_utterances: int,
    ) -> float:
        """Compute P_k metric."""

    def compute_window_diff(
        self,
        ground_truth: list[int],
        predicted: list[int],
        num_utterances: int,
        window_size: int | None = None,
    ) -> float:
        """Compute WindowDiff metric."""

    def evaluate_session(
        self,
        session_id: str,
        ground_truth: list[int],
        predicted: list[int],
        num_utterances: int,
        condition: str,
    ) -> EvalResult:
        """Evaluate segmentation for a single session."""

    def run_full_evaluation(
        self,
        segmentation_results: dict[str, list[int]],
    ) -> GateResult:
        """Run evaluation on all 30 lectures, compare baselines, check gate."""
```

**Baseline Implementations:**
```python
# src/eval/baselines.py
class RandomBaseline:
    def __init__(self, seed: int = 42):
        self.rng = np.random.RandomState(seed)

    def predict_boundaries(self, num_utterances: int, num_segments: int) -> list[int]:
        """Place boundaries at random positions."""


class FixedWindowBaseline:
    def __init__(self, window_size: int = 20):
        self.window_size = window_size

    def predict_boundaries(self, num_utterances: int) -> list[int]:
        """Place boundaries every window_size utterances."""


class TextTilingBaseline:
    def __init__(self):
        pass

    def predict_boundaries(
        self, embeddings: list[list[float]], threshold: float = 0.5
    ) -> list[int]:
        """Original TextTiling with fixed threshold."""
```

**Gate Check Script:**
```python
# scripts/eval_s29.py
#!/usr/bin/env python3
"""S29 HARD GATE evaluation script."""

import sys
from src.eval.segmentation_eval import SegmentationEvaluator, SegmentationEvalConfig


def main():
    config = SegmentationEvalConfig()
    evaluator = SegmentationEvaluator(config)

    # Load predictions from S28
    predictions = load_s28_predictions()

    # Run evaluation
    gate_result = evaluator.run_full_evaluation(predictions)

    # Log to MLflow
    log_to_mlflow(gate_result)

    # Print report
    print(f"Mean P_k: {gate_result.pk_mean:.4f} ± {gate_result.pk_std:.4f}")
    print(
        f"Mean WindowDiff: {gate_result.window_diff_mean:.4f} ± {gate_result.window_diff_std:.4f}"
    )
    print(f"Beats baselines: {gate_result.beats_baselines}")
    print(f"Gate passed: {gate_result.gate_passed}")
    print(f"Recommendation: {gate_result.recommendation}")

    if not gate_result.gate_passed:
        print("HARD GATE FAILED: P_k >= 0.30")
        print("DO NOT PROCEED TO S30 — revise segmentation approach")
        sys.exit(1)

    print("HARD GATE PASSED: P_k < 0.30")
    sys.exit(0)


if __name__ == "__main__":
    main()
```

**MLflow Experiment:**
```python
with mlflow.start_run(run_name=f"s29_eval_{date}"):
    mlflow.log_params(
        {
            "threshold_factor": config.threshold_factor,
            "num_lectures": 30,
            "gate_threshold": config.pk_threshold,
        }
    )
    mlflow.log_metrics(
        {
            "pk_mean": gate_result.pk_mean,
            "pk_std": gate_result.pk_std,
            "window_diff_mean": gate_result.window_diff_mean,
            "window_diff_std": gate_result.window_diff_std,
            "gate_passed": float(gate_result.gate_passed),
        }
    )
    mlflow.log_artifact("s29_eval_report.json")
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Default |
|----------|------|-------------|---------|
| `MLFLOW_TRACKING_URI` | string | MLflow server URL | `http://mlflow:5000` |
| `S05_LABELS_PATH` | string | S05 ground truth path | `lis-eval/labels/v1/boundaries/` |
| `S29_PK_THRESHOLD` | float | HARD GATE P_k threshold | `0.30` |

**Third-Party Integration Contracts:**
- segeval: P_k and WindowDiff computation
- MLflow: evaluation tracking
- DVC: S05 labels access

**Version Pins:**
- segeval >= 0.1.2
- MLflow >= 2.16.2

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T29.1 | V | `python scripts/eval_s29.py` (exits 0) | **GATE: P_k < 0.30 on held-out set** |
| T29.2 | V | `pytest tests/test_segmentation_eval.py::test_window_diff_recorded -v` | WindowDiff recorded alongside P_k |
| T29.3 | V | `pytest tests/test_segmentation_eval.py::test_beats_baselines -v` | Beats random and fixed-window baselines by clear margin |
| T29.4 | V | `pytest tests/test_segmentation_eval.py::test_per_condition -v` | Performance reported per condition (discussion-heavy vs monologue) |

**Test Case Details (Given/When/Then):**

**T29.1 — HARD GATE: P_k < 0.30**
- **Given:** segmentation results for 30 S05 lectures with ground truth boundaries
- **When:** P_k is computed across all held-out lectures
- **Then:** mean P_k < 0.30; script exits with code 0

**T29.2 — WindowDiff recorded**
- **Given:** same evaluation setup as T29.1
- **When:** evaluation completes
- **Then:** WindowDiff is computed and recorded alongside P_k in the eval report

**T29.3 — Beats baselines**
- **Given:** segmentation results and three baselines (random, fixed-window, TextTiling)
- **When:** P_k is compared across all methods
- **Then:** segmentation P_k is lower than random baseline by > 0.15 and lower than fixed-window by > 0.10

**T29.4 — Per-condition reporting**
- **Given:** 30 lectures split into discussion-heavy (15) and monologue (15) conditions
- **When:** evaluation is run
- **Then:** P_k and WindowDiff are reported separately for each condition; both below threshold

**Verification Commands:**
```bash
# Run full evaluation (includes gate check)
python scripts/eval_s29.py

# Run unit tests
uv run pytest tests/test_segmentation_eval.py -v -k "S29"

# Run linting
uv run mypy --strict src/eval/segmentation_eval.py && \
uv run ruff check src/eval/segmentation_eval.py
```

**Exit Criteria:**
- [ ] **T29.1 PASSES — P_k < 0.30 on held-out set (HARD GATE)**
- [ ] T29.2 passes — WindowDiff recorded alongside P_k
- [ ] **T29.3 PASSES — beats random and fixed-window baselines**
- [ ] T29.4 passes — per-condition results reported
- [ ] **T29.1 AND T29.3 pass before S30 can begin**
- [ ] If gate fails, segmentation approach is revised before clustering is built

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- segeval P_k implementation may differ from the original paper — verify with known fixtures
- Ground truth boundary positions must be utterance-level indices, not timestamps
- Random baseline with seed=42 must be reproducible; document the seed
- Threshold tuning on the full set risks overfitting — use held-out folds if >30 lectures available
- WindowDiff window size defaults to `ground_truth_segments / 2` — document this choice

**Fallback Instructions:**
- If P_k fails the gate (< 0.30):
  1. Check if S05 labels are correctly aligned with utterance positions
  2. Try different `threshold_factor` values (0.5, 1.0, 1.5, 2.0)
  3. Try different `min_segment_size` values (2, 3, 5)
  4. If still failing: consider different similarity metrics (dot product, L2)
  5. If still failing: revisit windowing config (S26) — W may be wrong
  6. If still failing: seek expert advice on segmentation approach
- If baselines outperform: investigate implementation — baselines may be too strong or segmentation too weak

**Rollback Procedure:**
- Gate failure is a PROJECT HALT for Block 4 — no code to revert
- Adjust parameters in `config/segmentation.yaml` and re-run
- No schema changes; no data changes
- MLflow tracks all experiments for comparison

---

### 9. Observability (if applicable)

**Metrics Added:**
- `s29_pk_score`: gauge of P_k per evaluation run
- `s29_window_diff_score`: gauge of WindowDiff per evaluation run
- `s29_gate_status`: gauge (1=pass, 0=fail) per evaluation run
- `s29_baseline_comparison`: gauge of segmentation vs baseline P_k difference

**Tracing/Logging:**
- Span: `eval.s29.full_evaluation` with attributes (num_lectures, pk_mean, gate_passed)
- Log: INFO on evaluation completion with full metrics
- Log: WARN if P_k close to threshold (0.25-0.35)
- Log: ERROR on gate failure with recommendation

**Alerts:**
- Gate failure: BLOCK S30 — project halt notification
- P_k > 0.35: immediate attention needed
- Baseline outperforms: investigate

---

### 10. Exit Checklist

- [ ] **All tests pass (T29.1, T29.2, T29.3, T29.4)**
- [ ] **HARD GATE: P_k < 0.30 on held-out set**
- [ ] **Beats random and fixed-window baselines**
- [ ] WindowDiff recorded alongside P_k
- [ ] Per-condition results (discussion-heavy vs monologue) reported
- [ ] Results logged to MLflow
- [ ] **If gate passes: S30 can proceed**
- [ ] **If gate fails: segmentation revised, loop back to S28**
