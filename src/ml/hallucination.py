"""Hallucination detection for ASR transcripts (S22).

Three independent detectors, each of which may fire on an utterance:
  - CrossModelDetector: primary/secondary ASR disagree (S21 `asr_agreement`)
  - RepetitionDetector: n-gram loop characteristic of Whisper degeneration
  - VADContradictionDetector: text present in a region VAD marked speechless

A detector that lacks its required signal (no `asr_agreement`, no VAD
regions) is skipped rather than firing - never raises, never guesses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class VADRegion:
    start_ms: int
    end_ms: int
    is_speech: bool


@dataclass
class HallucinationConfig:
    agreement_threshold: float = 0.5
    max_repeat_ngram: int = 3
    max_repeat_count: int = 3
    vad_margin_ms: int = 200
    min_utterance_length_ms: int = 500


@dataclass
class HallucinationResult:
    is_hallucination: bool
    detectors_fired: list[str] = field(default_factory=list)
    confidence: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def filter_reason(self) -> str | None:
        """Primary (first-firing) detector's filter_reason, per the spec's
        `asr_hallucination_<detector>` naming."""
        if not self.detectors_fired:
            return None
        return f"asr_hallucination_{self.detectors_fired[0]}"


class UtteranceLike(Protocol):
    text: str
    start_ms: int
    end_ms: int
    asr_agreement: float | None


def _normalize(text: str) -> list[str]:
    cleaned = re.sub(r"[^\w\s]", "", text.lower())
    return cleaned.split()


class CrossModelDetector:
    """Fires when the secondary ASR model disagrees strongly with the primary."""

    def __init__(self, agreement_threshold: float = 0.5) -> None:
        self.agreement_threshold = agreement_threshold

    def detect(self, utterance: UtteranceLike) -> tuple[bool, dict[str, Any]]:
        agreement = utterance.asr_agreement
        if agreement is None:
            return False, {"skipped": "no asr_agreement signal"}
        if not utterance.text.strip():
            return False, {"skipped": "empty text"}
        fired = agreement < self.agreement_threshold
        return fired, {"asr_agreement": agreement, "threshold": self.agreement_threshold}


class RepetitionDetector:
    """Fires on n-gram loops (Whisper degeneration), e.g. a phrase repeated
    beyond `max_repeat_count` times."""

    def __init__(self, max_repeat_ngram: int = 3, max_repeat_count: int = 3) -> None:
        self.max_repeat_ngram = max_repeat_ngram
        self.max_repeat_count = max_repeat_count

    def detect(self, utterance: UtteranceLike) -> tuple[bool, dict[str, Any]]:
        tokens = _normalize(utterance.text)
        for n in range(3, self.max_repeat_ngram + 3):
            if len(tokens) < n:
                continue
            ngrams = [tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)]
            counts: dict[tuple[str, ...], int] = {}
            for ngram in ngrams:
                counts[ngram] = counts.get(ngram, 0) + 1
            for ngram, count in counts.items():
                if count >= self.max_repeat_count:
                    return True, {"ngram": " ".join(ngram), "count": count, "n": n}
        return False, {}


class VADContradictionDetector:
    """Fires when an utterance's time span mostly overlaps a VAD-silence region."""

    def __init__(self, vad_margin_ms: int = 200, min_utterance_length_ms: int = 500) -> None:
        self.vad_margin_ms = vad_margin_ms
        self.min_utterance_length_ms = min_utterance_length_ms

    def detect(
        self, utterance: UtteranceLike, vad_regions: list[VADRegion] | None
    ) -> tuple[bool, dict[str, Any]]:
        if not vad_regions:
            return False, {"skipped": "no VAD regions"}

        duration = utterance.end_ms - utterance.start_ms
        if duration < self.min_utterance_length_ms:
            return False, {"skipped": "utterance too short"}

        silence_overlap_ms = 0
        for region in vad_regions:
            if region.is_speech:
                continue
            start = max(utterance.start_ms - self.vad_margin_ms, region.start_ms)
            end = min(utterance.end_ms + self.vad_margin_ms, region.end_ms)
            if end > start:
                silence_overlap_ms += end - start

        fraction = silence_overlap_ms / duration if duration > 0 else 0.0
        fired = fraction > 0.5
        return fired, {"silence_overlap_ms": silence_overlap_ms, "fraction": fraction}


class HallucinationDetector:
    """Orchestrates the three independent hallucination detectors."""

    def __init__(self, config: HallucinationConfig | None = None) -> None:
        self.config = config or HallucinationConfig()
        self.cross_model = CrossModelDetector(self.config.agreement_threshold)
        self.repetition = RepetitionDetector(
            self.config.max_repeat_ngram, self.config.max_repeat_count
        )
        self.vad_contradiction = VADContradictionDetector(
            self.config.vad_margin_ms, self.config.min_utterance_length_ms
        )

    def detect(
        self,
        utterance: UtteranceLike,
        vad_regions: list[VADRegion] | None = None,
    ) -> HallucinationResult:
        """Run all three detectors independently; a failure in one must never
        prevent the others from running."""
        fired: list[str] = []
        confidences: list[float] = []
        details: dict[str, Any] = {}

        try:
            cm_fired, cm_detail = self.cross_model.detect(utterance)
            details["cross_model"] = cm_detail
            if cm_fired:
                fired.append("cross_model")
                confidences.append(1.0 - (cm_detail.get("asr_agreement") or 0.0))
        except Exception as exc:  # pragma: no cover - defensive, per spec
            details["cross_model"] = {"error": str(exc)}

        try:
            rep_fired, rep_detail = self.repetition.detect(utterance)
            details["repetition"] = rep_detail
            if rep_fired:
                fired.append("repetition")
                confidences.append(1.0)
        except Exception as exc:  # pragma: no cover - defensive, per spec
            details["repetition"] = {"error": str(exc)}

        try:
            vad_fired, vad_detail = self.vad_contradiction.detect(utterance, vad_regions)
            details["vad_contradiction"] = vad_detail
            if vad_fired:
                fired.append("vad_contradiction")
                confidences.append(vad_detail.get("fraction", 1.0))
        except Exception as exc:  # pragma: no cover - defensive, per spec
            details["vad_contradiction"] = {"error": str(exc)}

        confidence = max(confidences) if confidences else 0.0
        return HallucinationResult(
            is_hallucination=bool(fired),
            detectors_fired=fired,
            confidence=confidence,
            details=details,
        )
