"""S42 HARD GATE - A1 evaluation against S05's 2,000 hand-labelled utterances.

Requires a real labelled corpus (one JSON record per utterance: `text`,
`is_relevant` ground truth, `category`, `outlier_score`, A1's predicted
`is_relevant`). If fewer than the required count is present, evaluation
functions return `None` rather than fabricating a result - the S05 corpus
was never delivered into this environment, see `docs/gaps.md`.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from src.services.filtering.relevance_filter import FilterCategory

GROUND_TRUTH_PATH = Path("lis-eval/labels/v1/relevance/utterances.json")
REQUIRED_UTTERANCES = 2000


class LabelledUtterance(BaseModel):
    utterance_id: str
    text: str
    category: FilterCategory
    ground_truth_relevant: bool
    predicted_relevant: bool
    outlier_score: float | None = None


class RelevanceEvalReport(BaseModel):
    precision_on_discard: float
    recall_on_off_topic: float
    core_content_discarded: int
    num_utterances: int
    per_category: dict[str, dict[str, int]]
    gate_precision_passed: bool
    gate_recall_passed: bool
    gate_zero_core_discarded_passed: bool

    @property
    def all_gates_passed(self) -> bool:
        return (
            self.gate_precision_passed
            and self.gate_recall_passed
            and self.gate_zero_core_discarded_passed
        )


PRECISION_THRESHOLD = 0.90
RECALL_THRESHOLD = 0.80


def load_labelled_utterances(
    ground_truth_path: Path = GROUND_TRUTH_PATH,
) -> list[LabelledUtterance]:
    """Load the S05 hand-labelled relevance corpus.

    Returns an empty list when the corpus doesn't exist in this environment
    (the honest, common case here) rather than raising.
    """
    if not ground_truth_path.exists():
        return []
    raw = json.loads(ground_truth_path.read_text())
    return [LabelledUtterance.model_validate(item) for item in raw]


def compute_confusion(
    labelled: list[LabelledUtterance],
) -> tuple[int, int, int, int]:
    """Return (tp_discard, fp_discard, tn_keep, fn_discard).

    "Discard" is the positive class here per S42's asymmetric-cost framing:
    predicted_relevant=False is a "discard" prediction.
    """
    tp = fp = tn = fn = 0
    for u in labelled:
        predicted_discard = not u.predicted_relevant
        actual_discard = not u.ground_truth_relevant
        if predicted_discard and actual_discard:
            tp += 1
        elif predicted_discard and not actual_discard:
            fp += 1
        elif not predicted_discard and actual_discard:
            fn += 1
        else:
            tn += 1
    return tp, fp, tn, fn


def evaluate_relevance_filter(
    ground_truth_path: Path = GROUND_TRUTH_PATH,
) -> RelevanceEvalReport | None:
    """Evaluate A1 against the S05 corpus. Returns None without a real corpus."""
    labelled = load_labelled_utterances(ground_truth_path)
    if len(labelled) < REQUIRED_UTTERANCES:
        return None
    return build_report(labelled)


def build_report(labelled: list[LabelledUtterance]) -> RelevanceEvalReport:
    tp, fp, _tn, fn = compute_confusion(labelled)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0

    core_discarded = sum(
        1
        for u in labelled
        if u.category == FilterCategory.CORE_CONTENT and not u.predicted_relevant
    )

    per_category: dict[str, dict[str, int]] = {}
    for cat in FilterCategory:
        subset = [u for u in labelled if u.category == cat]
        per_category[cat.value] = {
            "total": len(subset),
            "discarded": sum(1 for u in subset if not u.predicted_relevant),
            "misclassified": sum(
                1 for u in subset if u.predicted_relevant != u.ground_truth_relevant
            ),
        }

    return RelevanceEvalReport(
        precision_on_discard=precision,
        recall_on_off_topic=recall,
        core_content_discarded=core_discarded,
        num_utterances=len(labelled),
        per_category=per_category,
        gate_precision_passed=precision > PRECISION_THRESHOLD,
        gate_recall_passed=recall > RECALL_THRESHOLD,
        gate_zero_core_discarded_passed=core_discarded == 0,
    )


def outlier_score_ablation(
    labelled: list[LabelledUtterance],
) -> dict[str, float]:
    """T42.5 - correlate outlier_score with the discard ground truth.

    A crude but honest ablation: mean outlier_score for actually-off-topic
    utterances vs actually-on-topic ones. The feature is "informative" if
    the off-topic mean is meaningfully higher.
    """
    with_scores = [u for u in labelled if u.outlier_score is not None]
    off_topic: list[float] = [
        u.outlier_score
        for u in with_scores
        if not u.ground_truth_relevant and u.outlier_score is not None
    ]
    on_topic: list[float] = [
        u.outlier_score
        for u in with_scores
        if u.ground_truth_relevant and u.outlier_score is not None
    ]
    mean_off = sum(off_topic) / len(off_topic) if off_topic else 0.0
    mean_on = sum(on_topic) / len(on_topic) if on_topic else 0.0
    return {
        "mean_outlier_score_off_topic": mean_off,
        "mean_outlier_score_on_topic": mean_on,
        "separation": mean_off - mean_on,
    }
