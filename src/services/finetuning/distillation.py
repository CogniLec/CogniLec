"""S66 — A1 classifier distillation: dataset assembly, evaluation and swap.

The actual PEFT/Unsloth fine-tuning run needs a GPU-loaded base encoder
(gap #2 in docs/gaps.md - no GPU-loaded model in this environment), so
`DistilledClassifier` here is a thin injectable wrapper: real dataset
construction, real precision/recall/throughput evaluation logic, real
config-driven swap-with-fallback, all exercised against a fake classifier
in tests - the same injection pattern `FLUXGenerator` (S63) and
`RerankerClient` (S54) use for their own unavailable backends.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class LabelledUtterance:
    text: str
    is_relevant: bool
    source: str  # "llm_label" | "human_label_s05" | "correction"


def build_distillation_dataset(
    llm_labels: list[LabelledUtterance],
    human_labels: list[LabelledUtterance],
    corrections: list[LabelledUtterance],
) -> list[LabelledUtterance]:
    """Merge LLM-generated labels with human ground truth (S05 + S65).

    Human-sourced labels (S05's 2k hand-labelled set, and S65 corrections)
    always win over an LLM label for the same text - they are ground truth,
    not a second opinion.
    """
    by_text: dict[str, LabelledUtterance] = {u.text: u for u in llm_labels}
    for authoritative in (*human_labels, *corrections):
        by_text[authoritative.text] = authoritative
    return list(by_text.values())


class ClassifierBackend(Protocol):
    def predict(self, texts: list[str]) -> list[bool]:
        """Return `is_relevant` per text, same order."""
        ...


@dataclass(frozen=True)
class EvalResult:
    precision_discard: float
    recall_discard: float
    core_content_discarded: int


def evaluate_classifier(
    backend: ClassifierBackend,
    held_out: list[LabelledUtterance],
    core_content_flags: list[bool] | None = None,
) -> EvalResult:
    """Precision/recall on the *discard* (is_relevant=False) class.

    `core_content_flags[i]` marks whether `held_out[i]` is core lecture
    content - T66.4 requires zero of those ever predicted as discard,
    mirroring S42's T42.4 zero-core-content-discarded assertion.
    """
    texts = [u.text for u in held_out]
    predictions = backend.predict(texts)
    truth = [not u.is_relevant for u in held_out]  # True == "discard"
    predicted_discard = [not p for p in predictions]

    true_positives = sum(1 for t, p in zip(truth, predicted_discard, strict=True) if t and p)
    predicted_positives = sum(predicted_discard)
    actual_positives = sum(truth)

    precision = true_positives / predicted_positives if predicted_positives else 1.0
    recall = true_positives / actual_positives if actual_positives else 1.0

    core_discarded = 0
    if core_content_flags is not None:
        core_discarded = sum(
            1 for flag, p in zip(core_content_flags, predicted_discard, strict=True) if flag and p
        )

    return EvalResult(
        precision_discard=precision, recall_discard=recall, core_content_discarded=core_discarded
    )


def measure_throughput_ratio(
    small_backend: ClassifierBackend,
    large_backend: ClassifierBackend,
    texts: list[str],
) -> float:
    """Utterances/second for `small_backend` divided by `large_backend`."""
    start = time.perf_counter()
    small_backend.predict(texts)
    small_elapsed = max(time.perf_counter() - start, 1e-9)

    start = time.perf_counter()
    large_backend.predict(texts)
    large_elapsed = max(time.perf_counter() - start, 1e-9)

    small_rate = len(texts) / small_elapsed
    large_rate = len(texts) / large_elapsed
    return small_rate / large_rate


class A1ClassifierRouter:
    """Config-driven swap between the distilled classifier and the large-model fallback.

    T66.5: the classifier is swapped in by config, and the large model
    remains available as a fallback if the distilled classifier errors.
    """

    def __init__(
        self,
        distilled: ClassifierBackend,
        large_model_fallback: ClassifierBackend,
        use_distilled: bool = True,
    ) -> None:
        self._distilled = distilled
        self._fallback = large_model_fallback
        self._use_distilled = use_distilled

    def predict(self, texts: list[str]) -> list[bool]:
        if not self._use_distilled:
            return self._fallback.predict(texts)
        try:
            return self._distilled.predict(texts)
        except Exception:
            return self._fallback.predict(texts)
