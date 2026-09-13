"""Tests for S68 - ASR domain adaptation (T68.1-T68.6).

Fine-tuning Whisper/Canary needs a GPU-loaded base model (gap #2) and
10-20h of real transcribed local lecture audio (gap #1 - no such corpus
exists here). What's implemented for real: training-set assembly from
corrected transcripts, and the per-condition WER comparison the spec's
T68.1/T68.2 actually need, computed with a real Levenshtein-based WER
function over hand-constructed reference/hypothesis pairs with known edit
distances (same synthetic-but-real convention as S52-S54/S64's evaluation
sets).
"""

from __future__ import annotations

import pytest
from src.services.finetuning.asr_adaptation import (
    ConditionResult,
    TranscriptCorrection,
    build_training_set,
    evaluate_per_condition,
    word_error_rate,
)


def test_word_error_rate_identical_transcripts_is_zero():
    assert word_error_rate("the cat sat on the mat", "the cat sat on the mat") == 0.0


def test_word_error_rate_known_edit_distance():
    # 1 substitution ("cat" -> "dog") out of 6 reference words -> 1/6
    assert word_error_rate("the cat sat on the mat", "the dog sat on the mat") == pytest.approx(
        1 / 6
    )


def test_word_error_rate_empty_reference_and_hypothesis():
    assert word_error_rate("", "") == 0.0
    assert word_error_rate("", "extra words") == 1.0


def test_build_training_set_only_includes_actually_corrected_transcripts():
    corrections = [
        TranscriptCorrection("lecture_hall_a", "the resister value", "the resistor value"),
        TranscriptCorrection("lecture_hall_a", "no change here", "no change here"),
    ]
    training_set = build_training_set(corrections)
    assert len(training_set) == 1
    assert training_set[0]["reference"] == "the resistor value"
    assert training_set[0]["condition"] == "lecture_hall_a"


def test_t68_2_improvement_holds_across_all_conditions_not_just_best_represented():
    references = {
        "hall_a": ["the resistor value is high"],
        "hall_b": ["capacitor discharge rate"],
    }
    baseline = {
        "hall_a": ["the resister value is height"],  # 2 errors
        "hall_b": ["capacity discharge rate"],  # 1 error
    }
    adapted = {
        "hall_a": ["the resistor value is high"],  # 0 errors
        "hall_b": ["capacitor discharge rate"],  # 0 errors
    }
    results = evaluate_per_condition(references, baseline, adapted)
    assert len(results) == 2
    assert all(r.improved for r in results), "adapted WER must improve in every condition"


def test_condition_result_not_improved_when_wer_worsens():
    result = ConditionResult(condition="hall_c", baseline_wer=0.1, adapted_wer=0.3)
    assert result.improved is False


@pytest.mark.skip(
    reason=(
        "T68.1/T68.3/T68.4/T68.5 require an actual Whisper/Canary fine-tuning "
        "run on 10-20h of real transcribed local lecture audio and a "
        "GPU-loaded base model - no such corpus exists (gap #1) and no "
        "GPU-loaded ASR model is available (gap #2), docs/gaps.md. The WER "
        "computation and per-condition comparison logic those tests would "
        "use is real and tested above against hand-constructed pairs."
    )
)
def test_t68_1_wer_improves_over_baseline_on_held_out_local_audio():
    pass
