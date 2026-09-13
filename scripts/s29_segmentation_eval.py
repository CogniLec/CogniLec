#!/usr/bin/env python3
"""S29 HARD GATE — evaluate S28 segmentation against S05's 30 hand-marked lectures.

Requires real hand-labelled boundary data under `lis-eval/labels/v1/boundaries/`
(one file per lecture, `{"boundaries": [utt_idx, ...], "n_utterances": N}`).
If fewer than 30 labelled lectures are present, this script CANNOT honestly
claim the gate passed - see `tests/test_s29_segmentation_gate.py` for how
the test suite handles that (skip, not a fabricated pass).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from src.eval.harness import DatasetType, run_eval
from src.eval.segmentation_report import (
    SegmentationEvalReport,
    build_report,
    fixed_window_segmentation,
    random_segmentation,
)
from src.ml.clustering.segmentation import segment_session

GROUND_TRUTH_DIR = Path("lis-eval/labels/v1/boundaries")
REQUIRED_LECTURES = 30


class _Utt:
    def __init__(self, i: int) -> None:
        self.id = i


def load_labelled_lectures(ground_truth_dir: Path = GROUND_TRUTH_DIR) -> list[dict[str, object]]:
    """Load hand-marked lectures with `boundaries` (utterance indices) and `n_utterances`.

    Returns an empty list if the directory doesn't contain the expected
    per-lecture boundary-annotation format (S05's real corpus was not
    delivered into this environment - see `docs/gaps.md`).
    """
    if not ground_truth_dir.exists():
        return []
    lectures = []
    for path in sorted(ground_truth_dir.glob("*.json")):
        data = json.loads(path.read_text())
        if isinstance(data, dict) and "boundaries" in data and "n_utterances" in data:
            lectures.append(data)
    return lectures


def _avg(xs: list[float]) -> float:
    return sum(xs) / len(xs)


def evaluate_segmentation(
    ground_truth_dir: Path = GROUND_TRUTH_DIR,
    threshold_percentile: float = 25.0,
) -> SegmentationEvalReport | None:
    """Evaluate segmentation P_k/WindowDiff against hand-marked boundaries.

    Returns `None` if there isn't a real 30-lecture ground-truth corpus to
    evaluate against, rather than fabricating a result.
    """
    lectures = load_labelled_lectures(ground_truth_dir)
    if len(lectures) < REQUIRED_LECTURES:
        return None

    pks: list[float] = []
    wds: list[float] = []
    random_pks: list[float] = []
    fixed_pks: list[float] = []
    for lecture in lectures:
        n = int(lecture["n_utterances"])  # type: ignore[call-overload]
        ref_boundaries = lecture["boundaries"]
        embeddings = lecture["embeddings"]  # precomputed windowed embeddings

        utterances = [_Utt(i) for i in range(n)]
        result = segment_session(
            utterances,  # type: ignore[arg-type]
            embeddings,  # type: ignore[arg-type]
            threshold_percentile=threshold_percentile,
        )
        pred_boundaries = [seg.end_idx + 1 for seg in result.segments[:-1]]

        out = run_eval(DatasetType.SEGMENTATION, [ref_boundaries], [pred_boundaries])
        pks.append(out.pk)  # type: ignore[arg-type]
        wds.append(out.window_diff)  # type: ignore[arg-type]

        rand_b = random_segmentation(n, len(ref_boundaries))  # type: ignore[arg-type]
        random_out = run_eval(DatasetType.SEGMENTATION, [ref_boundaries], [rand_b])
        random_pks.append(random_out.pk)  # type: ignore[arg-type]
        fixed_b = fixed_window_segmentation(n)
        fixed_out = run_eval(DatasetType.SEGMENTATION, [ref_boundaries], [fixed_b])
        fixed_pks.append(fixed_out.pk)  # type: ignore[arg-type]

    return build_report(
        pk_score=_avg(pks),
        window_diff=_avg(wds),
        baseline_random_pk=_avg(random_pks),
        baseline_fixed_window_pk=_avg(fixed_pks),
        threshold_used=threshold_percentile,
        num_lectures_evaluated=len(lectures),
    )


if __name__ == "__main__":
    report = evaluate_segmentation()
    if report is None:
        print(
            f"SKIP: fewer than {REQUIRED_LECTURES} hand-labelled lectures found under "
            f"{GROUND_TRUTH_DIR} - cannot honestly evaluate the S29 gate in this environment."
        )
        sys.exit(0)
    print(report.model_dump_json(indent=2))
    sys.exit(0 if report.gate_passed and report.beats_baselines else 1)
