"""Tests for S42 HARD GATE - A1 evaluation & threshold calibration (T42.1-T42.5).

ENVIRONMENT / HONESTY CAVEAT (read before trusting any pass/fail here):

S42 requires evaluating A1 against S05's 2,000 hand-labelled utterances
(precision on discard > 0.90, recall on off-topic > 0.80, zero core-content
utterances discarded). That corpus was never delivered into this
environment - see `docs/gaps.md` gap #1/#6, and `tests/test_s29_segmentation_gate.py`
for the identical situation one block earlier. No file exists at
`lis-eval/labels/v1/relevance/utterances.json`.

Consequently T42.1, T42.2 and T42.4 (the actual gate assertions) CANNOT be
honestly evaluated here and are skipped rather than faked. What IS genuinely
tested: `src/eval/relevance_evaluation.py`'s real precision/recall/confusion
math and per-category error analysis, using synthetic labelled data.
"""

from __future__ import annotations

import pytest
from src.eval.relevance_evaluation import (
    PRECISION_THRESHOLD,
    RECALL_THRESHOLD,
    LabelledUtterance,
    build_report,
    compute_confusion,
    evaluate_relevance_filter,
    load_labelled_utterances,
    outlier_score_ablation,
)
from src.services.filtering.relevance_filter import FilterCategory

GATE_SKIP_REASON = (
    "S05's real 2,000-utterance hand-labelled relevance corpus is not "
    "present in this environment (no file at "
    "lis-eval/labels/v1/relevance/utterances.json). Cannot honestly "
    "evaluate the precision>0.90 / recall>0.80 / zero-core-discarded gates "
    "without it."
)


def _make(
    n_relevant_core: int = 5,
    n_offtopic_correctly_discarded: int = 8,
    n_offtopic_wrongly_kept: int = 2,
    n_relevant_wrongly_discarded: int = 0,
) -> list[LabelledUtterance]:
    items: list[LabelledUtterance] = []
    for i in range(n_relevant_core):
        items.append(
            LabelledUtterance(
                utterance_id=f"core-{i}",
                text="t",
                category=FilterCategory.CORE_CONTENT,
                ground_truth_relevant=True,
                predicted_relevant=True,
                outlier_score=0.1,
            )
        )
    for i in range(n_relevant_wrongly_discarded):
        items.append(
            LabelledUtterance(
                utterance_id=f"core-lost-{i}",
                text="t",
                category=FilterCategory.CORE_CONTENT,
                ground_truth_relevant=True,
                predicted_relevant=False,
                outlier_score=0.5,
            )
        )
    for i in range(n_offtopic_correctly_discarded):
        items.append(
            LabelledUtterance(
                utterance_id=f"aside-{i}",
                text="t",
                category=FilterCategory.ASIDE,
                ground_truth_relevant=False,
                predicted_relevant=False,
                outlier_score=0.9,
            )
        )
    for i in range(n_offtopic_wrongly_kept):
        items.append(
            LabelledUtterance(
                utterance_id=f"aside-kept-{i}",
                text="t",
                category=FilterCategory.ASIDE,
                ground_truth_relevant=False,
                predicted_relevant=True,
                outlier_score=0.6,
            )
        )
    return items


class TestGroundTruthAvailability:
    def test_real_s05_relevance_corpus_not_present(self) -> None:
        labelled = load_labelled_utterances()
        assert len(labelled) < 2000

    def test_evaluate_returns_none_without_corpus(self) -> None:
        assert evaluate_relevance_filter() is None


@pytest.mark.skip(reason=GATE_SKIP_REASON)
class TestT421T422T424HardGate:
    def test_precision_on_discard_above_threshold(self) -> None:
        raise NotImplementedError

    def test_recall_on_offtopic_above_threshold(self) -> None:
        raise NotImplementedError

    def test_zero_core_content_discarded(self) -> None:
        raise NotImplementedError


class TestConfusionAndReportMath:
    """Genuinely testable parts of S42 that don't require the S05 corpus."""

    def test_compute_confusion_counts(self) -> None:
        labelled = _make(
            n_relevant_core=5,
            n_offtopic_correctly_discarded=8,
            n_offtopic_wrongly_kept=2,
            n_relevant_wrongly_discarded=0,
        )
        tp, fp, tn, fn = compute_confusion(labelled)
        assert tp == 8
        assert fp == 0
        assert tn == 5
        assert fn == 2

    def test_report_passes_gates_on_strong_synthetic_data(self) -> None:
        labelled = _make(
            n_relevant_core=100,
            n_offtopic_correctly_discarded=95,
            n_offtopic_wrongly_kept=5,
            n_relevant_wrongly_discarded=0,
        )
        report = build_report(labelled)
        assert report.precision_on_discard > PRECISION_THRESHOLD
        assert report.recall_on_off_topic > RECALL_THRESHOLD
        assert report.gate_zero_core_discarded_passed is True
        assert report.all_gates_passed is True

    def test_report_fails_when_core_content_discarded(self) -> None:
        labelled = _make(n_relevant_wrongly_discarded=1)
        report = build_report(labelled)
        assert report.core_content_discarded == 1
        assert report.gate_zero_core_discarded_passed is False
        assert report.all_gates_passed is False

    def test_per_category_error_analysis_present(self) -> None:
        labelled = _make()
        report = build_report(labelled)
        assert set(report.per_category) == {c.value for c in FilterCategory}
        assert report.per_category[FilterCategory.CORE_CONTENT.value]["total"] == 5

    def test_outlier_score_ablation_shows_separation(self) -> None:
        labelled = _make()
        ablation = outlier_score_ablation(labelled)
        assert ablation["mean_outlier_score_off_topic"] > ablation["mean_outlier_score_on_topic"]
        assert ablation["separation"] > 0
