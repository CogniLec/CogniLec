"""S68 — ASR domain adaptation: training-set assembly and per-condition WER evaluation.

Actual Whisper/Canary fine-tuning needs a GPU-loaded base model and 10-20h
of transcribed local audio (gap #1: no real S04/S05 corpus; gap #2: no
GPU-loaded model) - neither exists in this sandbox. What's implemented for
real here is the part that doesn't need either: building the training set
from corrected transcripts (an ASR-transcript-edit correction type, the
same shape as S65's other five capture points), and the per-condition WER
comparison logic the spec's T68.1/T68.2 need, computed with a real
Levenshtein-based WER function against injected (not fabricated) reference
and hypothesis transcripts.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TranscriptCorrection:
    condition: str  # e.g. room/lecturer/accent bucket, per S04's condition matrix
    original_transcript: str
    corrected_transcript: str


def build_training_set(corrections: list[TranscriptCorrection]) -> list[dict[str, str]]:
    """One training example per corrected transcript, keyed by condition."""
    return [
        {"condition": c.condition, "reference": c.corrected_transcript}
        for c in corrections
        if c.corrected_transcript != c.original_transcript
    ]


def word_error_rate(reference: str, hypothesis: str) -> float:
    """Standard WER: edit distance over reference words, divided by reference length."""
    ref_words = reference.split()
    hyp_words = hypothesis.split()
    n, m = len(ref_words), len(hyp_words)
    if n == 0:
        return 0.0 if m == 0 else 1.0

    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if ref_words[i - 1] == hyp_words[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = 1 + min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1])
    return dp[n][m] / n


@dataclass(frozen=True)
class ConditionResult:
    condition: str
    baseline_wer: float
    adapted_wer: float

    @property
    def improved(self) -> bool:
        return self.adapted_wer < self.baseline_wer


def evaluate_per_condition(
    references_by_condition: dict[str, list[str]],
    baseline_hypotheses_by_condition: dict[str, list[str]],
    adapted_hypotheses_by_condition: dict[str, list[str]],
) -> list[ConditionResult]:
    """Compare baseline vs. adapted WER, one row per S04 condition.

    T68.2 requires improvement to hold across *all* conditions, not just
    the best-represented one - this returns every condition's numbers so
    the caller can assert that directly rather than trusting an aggregate.
    """
    results = []
    for condition, refs in references_by_condition.items():
        baseline_hyps = baseline_hypotheses_by_condition[condition]
        adapted_hyps = adapted_hypotheses_by_condition[condition]
        baseline_wer = sum(
            word_error_rate(r, h) for r, h in zip(refs, baseline_hyps, strict=True)
        ) / len(refs)
        adapted_wer = sum(
            word_error_rate(r, h) for r, h in zip(refs, adapted_hyps, strict=True)
        ) / len(refs)
        results.append(ConditionResult(condition, baseline_wer, adapted_wer))
    return results
