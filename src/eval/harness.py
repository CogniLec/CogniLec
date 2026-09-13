#!/usr/bin/env python3
"""Evaluation Harness — Single entry point for all LIS evaluations.

Implements: jiwer (WER), segeval (P_k, WindowDiff), sklearn (purity, V-measure, kappa)
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

import jiwer
import numpy as np
import segeval
from pydantic import BaseModel, Field
from sklearn.metrics import cohen_kappa_score, v_measure_score


def purity_score(reference: list[int], predictions: list[int]) -> float:
    """Purity = sum(max overlap per predicted cluster) / total samples."""
    ref = np.asarray(reference)
    pred = np.asarray(predictions)
    unique_pred = np.unique(pred)
    score = 0
    for cluster in unique_pred:
        mask = pred == cluster
        score += int(max(int(np.sum(ref[mask] == lbl)) for lbl in np.unique(ref)))
    return float(score / len(ref))


class DatasetType(StrEnum):
    WER = "wer"
    SEGMENTATION = "segmentation"
    CLUSTERING = "clustering"
    RELEVANCE = "relevance"


class EvalInput(BaseModel):
    dataset: DatasetType
    reference: list[str | int | list[int]] = Field(description="Ground truth")
    predictions: list[str | int | list[int]] = Field(description="Model output")


class EvalOutput(BaseModel):
    wer: float | None = None
    cer: float | None = None
    pk: float | None = None
    window_diff: float | None = None
    purity: float | None = None
    v_measure: float | None = None
    kappa: float | None = None


def run_eval(dataset: DatasetType, reference: list[Any], predictions: list[Any]) -> EvalOutput:
    """Single entry point for all evaluations.

    Args:
        dataset: Type of evaluation
        reference: Ground truth (format depends on dataset)
        predictions: Model predictions (same format as reference)

    Returns:
        EvalOutput with relevant metrics populated
    """
    if dataset == DatasetType.WER:
        return _eval_wer(reference, predictions)
    elif dataset == DatasetType.SEGMENTATION:
        return _eval_segmentation(reference, predictions)
    elif dataset == DatasetType.CLUSTERING:
        return _eval_clustering(reference, predictions)
    elif dataset == DatasetType.RELEVANCE:
        return _eval_relevance(reference, predictions)
    else:
        raise ValueError(f"Unknown dataset type: {dataset}")


def _eval_wer(reference: list[str], predictions: list[str]) -> EvalOutput:
    """Word Error Rate using jiwer with whisper-normalizer."""
    # Apply whisper-normalizer transformations
    transform = jiwer.Compose(
        [
            jiwer.ToLowerCase(),
            jiwer.RemovePunctuation(),
            jiwer.RemoveWhiteSpace(replace_by_space=True),
            jiwer.Strip(),
            jiwer.RemoveMultipleSpaces(),
        ]
    )

    ref_clean = [transform(r) for r in reference]
    pred_clean = [transform(p) for p in predictions]

    wer = jiwer.wer(ref_clean, pred_clean)
    cer = jiwer.cer(ref_clean, pred_clean)

    return EvalOutput(wer=wer, cer=cer)


def _eval_segmentation(reference: list[list[int]], predictions: list[list[int]]) -> EvalOutput:
    """Segmentation evaluation using segeval (P_k, WindowDiff).

    Args:
        reference: List of segment boundary indices (0-based, utterance indices)
        predictions: Same format

    Returns:
        EvalOutput with pk and window_diff
    """

    # Convert to segeval format: list of segment lengths
    def boundaries_to_lengths(boundaries: list[int], total_utterances: int) -> list[int]:
        if not boundaries:
            return [total_utterances]
        lengths: list[int] = []
        prev = 0
        for b in sorted(boundaries):
            lengths.append(b - prev)
            prev = b
        lengths.append(total_utterances - prev)
        return lengths

    flat_ref: list[int] = [b for group in reference for b in group]
    flat_pred: list[int] = [b for group in predictions for b in group]
    total = max(max(flat_ref) if flat_ref else 0, max(flat_pred) if flat_pred else 0) + 1
    ref_lengths = boundaries_to_lengths(flat_ref, total)
    pred_lengths = boundaries_to_lengths(flat_pred, total)

    pk = segeval.pk(ref_lengths, pred_lengths)
    wd = segeval.window_diff(ref_lengths, pred_lengths)

    return EvalOutput(pk=pk, window_diff=wd)


def _eval_clustering(reference: list[int], predictions: list[int]) -> EvalOutput:
    """Clustering evaluation (purity, V-measure).

    Args:
        reference: Ground truth cluster labels (integers)
        predictions: Predicted cluster labels (integers)
    """
    purity = purity_score(reference, predictions)
    v_measure = v_measure_score(reference, predictions)

    return EvalOutput(purity=purity, v_measure=v_measure)


def _eval_relevance(reference: list[int], predictions: list[int]) -> EvalOutput:
    """Relevance classification evaluation (Cohen's kappa).

    Args:
        reference: Ground truth labels (0=off_topic, 1=on_topic)
        predictions: Predicted labels (0=off_topic, 1=on_topic)
    """
    kappa = cohen_kappa_score(reference, predictions)

    return EvalOutput(kappa=kappa)


# Known fixtures for unit testing
WER_FIXTURE = {
    "reference": ["the quick brown fox", "jumps over the lazy dog"],
    "predictions": ["the quick brown fox", "jumps over a lazy dog"],
    "expected_wer": 1 / 9,  # 1 substitution out of 9 words
}

SEGEVAL_FIXTURES = {
    "identical": {
        "reference": [[3, 5, 7]],  # boundaries at utterances 3, 5, 7
        "predictions": [[3, 5, 7]],
        "expected_pk": 0.0,
    },
    "inverted": {
        "reference": [[3, 5, 7]],
        "predictions": [[2, 4, 6]],  # shifted by 1
        "expected_pk_gt": 0.5,
    },
}


if __name__ == "__main__":
    # Quick sanity checks
    print("Testing WER fixture...")
    ref: list[str] = WER_FIXTURE["reference"]  # type: ignore[assignment]
    pred: list[str] = WER_FIXTURE["predictions"]  # type: ignore[assignment]
    result = run_eval(DatasetType.WER, ref, pred)
    print(f"  WER: {result.wer:.4f} (expected ~{WER_FIXTURE['expected_wer']:.4f})")

    print("Testing segmentation fixtures...")
    for name, fixture in SEGEVAL_FIXTURES.items():
        seg_ref: list[list[int]] = fixture["reference"]  # type: ignore[assignment]
        seg_pred: list[list[int]] = fixture["predictions"]  # type: ignore[assignment]
        result = run_eval(DatasetType.SEGMENTATION, seg_ref, seg_pred)
        print(f"  {name}: P_k={result.pk:.4f}")
        if name == "identical":
            assert result.pk == 0.0, f"Expected 0.0, got {result.pk}"
        elif name == "inverted":
            assert result.pk is not None and result.pk > 0.5, f"Expected >0.5, got {result.pk}"

    print("All sanity checks passed!")
