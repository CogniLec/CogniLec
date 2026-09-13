"""Tests for S29 HARD GATE - segmentation evaluation (T29.1-T29.4).

ENVIRONMENT / HONESTY CAVEAT (read before trusting any pass/fail here):

S05's real 30 hand-marked lectures (with per-utterance boundary ground truth
and precomputed windowed embeddings) were never delivered into this
environment. `lis-eval/labels/v1/boundaries/sample.json` that DOES exist is
a single Label-Studio *audio-timestamp* rectangle annotation stub (percent-
of-duration spans on one lecture's audio), not the 30-lecture, utterance-
indexed boundary corpus the S29 spec requires - see `docs/gaps.md`.

Consequently T29.1 (GATE: P_k < 0.30) and T29.3 (beats baselines) CANNOT be
honestly evaluated here. This mirrors how S19/S20 handled their own unmet
real-data dependencies (`@pytest.mark.skip` with a clear reason) rather than
fabricating a passing P_k score. What IS genuinely tested: the baseline
generators (random/fixed-window) and the report/gate-threshold math, using
`src/eval/harness.py`'s real segeval-backed P_k/WindowDiff computation on
synthetic boundaries.
"""

from __future__ import annotations

import pytest
from scripts.s29_segmentation_eval import evaluate_segmentation, load_labelled_lectures
from src.eval.harness import DatasetType, run_eval
from src.eval.segmentation_report import (
    build_report,
    fixed_window_segmentation,
    random_segmentation,
)

GATE_SKIP_REASON = (
    "S05's real 30 hand-marked lectures with utterance-indexed boundary "
    "ground truth are not present in this environment (only a 1-lecture "
    "Label-Studio audio-timestamp stub exists at "
    "lis-eval/labels/v1/boundaries/sample.json, which is not the required "
    "corpus format). Cannot honestly evaluate the P_k < 0.30 gate without it."
)


class TestGroundTruthAvailability:
    def test_real_s05_corpus_not_present(self) -> None:
        """Documents the actual state of this environment: fewer than 30
        labelled lectures in the expected format exist, so the gate below
        is skipped rather than faked."""
        lectures = load_labelled_lectures()
        assert len(lectures) < 30

    def test_evaluate_segmentation_returns_none_without_corpus(self) -> None:
        result = evaluate_segmentation()
        assert result is None


@pytest.mark.skip(reason=GATE_SKIP_REASON)
class TestT291T293HardGate:
    def test_pk_below_threshold(self) -> None:
        raise NotImplementedError

    def test_beats_baselines(self) -> None:
        raise NotImplementedError


class TestBaselineGeneratorsAndReportMath:
    """Genuinely testable parts of S29 that don't require the S05 corpus."""

    def test_random_segmentation_boundary_count(self) -> None:
        boundaries = random_segmentation(100, 5, seed=1)
        assert len(boundaries) == 5
        assert boundaries == sorted(boundaries)
        assert all(0 < b < 100 for b in boundaries)

    def test_fixed_window_segmentation(self) -> None:
        boundaries = fixed_window_segmentation(100, window=20)
        assert boundaries == [20, 40, 60, 80]

    def test_report_gate_passes_below_threshold(self) -> None:
        report = build_report(
            pk_score=0.20,
            window_diff=0.25,
            baseline_random_pk=0.45,
            baseline_fixed_window_pk=0.40,
            threshold_used=25.0,
            num_lectures_evaluated=30,
        )
        assert report.gate_passed is True
        assert report.beats_baselines is True

    def test_report_gate_fails_above_threshold(self) -> None:
        report = build_report(
            pk_score=0.35,
            window_diff=0.40,
            baseline_random_pk=0.45,
            baseline_fixed_window_pk=0.40,
            threshold_used=25.0,
            num_lectures_evaluated=30,
        )
        assert report.gate_passed is False

    def test_report_fails_beats_baselines_when_too_close(self) -> None:
        """Margin (0.05) guards against trivially passing near a baseline."""
        report = build_report(
            pk_score=0.38,
            window_diff=0.40,
            baseline_random_pk=0.40,
            baseline_fixed_window_pk=0.42,
            threshold_used=25.0,
            num_lectures_evaluated=30,
        )
        assert report.beats_baselines is False

    def test_segeval_harness_identical_boundaries_zero_pk(self) -> None:
        out = run_eval(DatasetType.SEGMENTATION, [[3, 5, 7]], [[3, 5, 7]])
        assert out.pk == 0.0
