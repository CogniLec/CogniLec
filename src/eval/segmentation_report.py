"""S29 — segmentation evaluation report schema and baselines (HARD GATE)."""

from __future__ import annotations

import random

from pydantic import BaseModel


class ConditionMetrics(BaseModel):
    pk: float
    window_diff: float
    num_lectures: int


class SegmentationEvalReport(BaseModel):
    pk_score: float
    window_diff: float
    gate_passed: bool
    baseline_random_pk: float
    baseline_fixed_window_pk: float
    beats_baselines: bool
    per_condition: dict[str, ConditionMetrics] = {}
    threshold_used: float
    num_lectures_evaluated: int


PK_GATE_THRESHOLD = 0.30
BASELINE_MARGIN = 0.05


def random_segmentation(n_utterances: int, n_boundaries: int, seed: int = 42) -> list[int]:
    """S29 §5.3 baseline: uniformly random boundary placement."""
    rng = random.Random(seed)
    if n_utterances <= 1 or n_boundaries <= 0:
        return []
    candidates = list(range(1, n_utterances))
    rng.shuffle(candidates)
    return sorted(candidates[: min(n_boundaries, len(candidates))])


def fixed_window_segmentation(n_utterances: int, window: int = 20) -> list[int]:
    """S29 §5.3 baseline: a boundary every `window` utterances."""
    return list(range(window, n_utterances, window))


def build_report(
    pk_score: float,
    window_diff: float,
    baseline_random_pk: float,
    baseline_fixed_window_pk: float,
    threshold_used: float,
    num_lectures_evaluated: int,
    per_condition: dict[str, ConditionMetrics] | None = None,
) -> SegmentationEvalReport:
    gate_passed = pk_score < PK_GATE_THRESHOLD
    beats_baselines = pk_score < min(baseline_random_pk, baseline_fixed_window_pk) - BASELINE_MARGIN
    return SegmentationEvalReport(
        pk_score=pk_score,
        window_diff=window_diff,
        gate_passed=gate_passed,
        baseline_random_pk=baseline_random_pk,
        baseline_fixed_window_pk=baseline_fixed_window_pk,
        beats_baselines=beats_baselines,
        per_condition=per_condition or {},
        threshold_used=threshold_used,
        num_lectures_evaluated=num_lectures_evaluated,
    )
