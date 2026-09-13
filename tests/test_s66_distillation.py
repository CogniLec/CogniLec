"""Tests for S66 - A1 classifier distillation (T66.1-T66.6).

No GPU-loaded encoder is available to actually run Unsloth/PEFT
distillation training (gap #2), so `ClassifierBackend` is exercised via
fake in-memory backends here, the same injection pattern S54/S63 use for
their own unavailable models. Dataset merging, precision/recall
computation, throughput comparison and config-driven swap-with-fallback
are all real logic, genuinely exercised.

T66.6 (A/B on live sessions shows no quality regression) is an honest skip
- there is no live-session pipeline with real users in this sandbox (same
gap class as S56's human-in-the-loop evaluations).
"""

from __future__ import annotations

import time

import pytest
from src.services.finetuning.distillation import (
    A1ClassifierRouter,
    LabelledUtterance,
    build_distillation_dataset,
    evaluate_classifier,
    measure_throughput_ratio,
)


class FakeClassifier:
    def __init__(self, decisions: dict[str, bool], delay_s: float = 0.0, fail: bool = False):
        self._decisions = decisions
        self._delay_s = delay_s
        self._fail = fail

    def predict(self, texts: list[str]) -> list[bool]:
        if self._fail:
            raise RuntimeError("classifier backend unavailable")
        if self._delay_s:
            time.sleep(self._delay_s)
        return [self._decisions.get(t, True) for t in texts]


def test_t65_style_dataset_merge_human_labels_win_over_llm_labels():
    llm = [
        LabelledUtterance("hello", True, "llm_label"),
        LabelledUtterance("bye", True, "llm_label"),
    ]
    human = [LabelledUtterance("hello", False, "human_label_s05")]
    corrections = [LabelledUtterance("bye", False, "correction")]
    merged = build_distillation_dataset(llm, human, corrections)
    by_text = {u.text: u for u in merged}
    assert by_text["hello"].is_relevant is False
    assert by_text["hello"].source == "human_label_s05"
    assert by_text["bye"].is_relevant is False
    assert by_text["bye"].source == "correction"


def test_t66_1_and_t66_2_precision_recall_within_target_of_large_model():
    held_out = [
        LabelledUtterance("core explanation one", True, "human_label_s05"),
        LabelledUtterance("core explanation two", True, "human_label_s05"),
        LabelledUtterance("admin announcement", False, "human_label_s05"),
        LabelledUtterance("off topic aside", False, "human_label_s05"),
    ]
    large_model = FakeClassifier(
        {"admin announcement": False, "off topic aside": False}, delay_s=0.01
    )
    distilled = FakeClassifier({"admin announcement": False, "off topic aside": False}, delay_s=0.0)

    large_result = evaluate_classifier(large_model, held_out)
    distilled_result = evaluate_classifier(distilled, held_out)

    assert abs(distilled_result.precision_discard - large_result.precision_discard) <= 0.02
    assert abs(distilled_result.recall_discard - large_result.recall_discard) <= 0.03


def test_t66_4_zero_core_content_discarded():
    held_out = [
        LabelledUtterance("core content", True, "human_label_s05"),
        LabelledUtterance("tangent", False, "human_label_s05"),
    ]
    core_flags = [True, False]
    classifier = FakeClassifier({"tangent": False})
    result = evaluate_classifier(classifier, held_out, core_content_flags=core_flags)
    assert result.core_content_discarded == 0


def test_t66_3_throughput_at_least_20x():
    texts = ["utterance"] * 5
    small = FakeClassifier({}, delay_s=0.0)
    large = FakeClassifier({}, delay_s=0.02)
    ratio = measure_throughput_ratio(small, large, texts)
    assert ratio >= 20


def test_t66_5_classifier_swapped_by_config_large_model_fallback_available():
    distilled = FakeClassifier({"x": False})
    large = FakeClassifier({"x": True})

    router_on = A1ClassifierRouter(distilled, large, use_distilled=True)
    assert router_on.predict(["x"]) == [False]

    router_off = A1ClassifierRouter(distilled, large, use_distilled=False)
    assert router_off.predict(["x"]) == [True]


def test_t66_5_failed_distilled_classifier_falls_back_to_large_model():
    distilled = FakeClassifier({}, fail=True)
    large = FakeClassifier({"x": True})
    router = A1ClassifierRouter(distilled, large, use_distilled=True)
    assert router.predict(["x"]) == [True]


@pytest.mark.skip(
    reason=(
        "T66.6 needs a live A/B on real user sessions with real note quality "
        "outcomes - no live-session pipeline with real users exists in this "
        "sandbox (same gap class as S56's human-in-the-loop evaluations, "
        "docs/gaps.md)."
    )
)
def test_t66_6_ab_on_live_sessions_no_quality_regression():
    pass
