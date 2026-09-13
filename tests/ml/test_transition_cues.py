"""S34 — transition cue detection tests (T34.1, T34.4; T34.2/T34.3 honest-skip)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest
from src.ml.transition_cues import (
    apply_boundary_boosts,
    detect_cues,
    load_cue_patterns,
)

CORPUS_SKIP_REASON = (
    "S05's hand-marked lecture corpus with transition-cue ground truth "
    "annotations is not present in this environment (only a 1-lecture "
    "Label-Studio audio-timestamp stub exists, per docs/gaps.md and the "
    "existing S29 precedent in tests/test_s29_segmentation_gate.py). "
    "T34.2 (precision > 0.85) and T34.3 (P_k improvement vs S29 baseline) "
    "cannot be honestly evaluated without the annotated 30-lecture corpus."
)


@dataclass
class FakeUtterance:
    id: uuid.UUID
    seq: int
    text: str


@dataclass
class FakeSegment:
    id: uuid.UUID
    start_utt_seq: int
    boundary_score: float | None


@pytest.mark.unit
class TestT341PatternsMatchIntendedPhrasings:
    @pytest.mark.parametrize(
        "pattern_id,phrase",
        [
            ("moving_on", "Moving on to the next section"),
            ("moving_on", "Let's move on to calculus"),
            ("next_topic", "Next we'll look at derivatives"),
            ("completes_section", "That completes our discussion of limits"),
            ("break_reference", "Let's take a break before we continue"),
            ("today_we_cover", "Today we'll be covering linear algebra"),
        ],
    )
    def test_pattern_matches_intended_phrase(self, pattern_id: str, phrase: str) -> None:
        session_id = uuid.uuid4()
        utt = FakeUtterance(uuid.uuid4(), 0, phrase)

        result = detect_cues(session_id, [utt])

        assert any(m.pattern_id == pattern_id for m in result.matches), (
            f"expected {pattern_id} to match {phrase!r}, got {result.matches}"
        )

    def test_no_false_positive_on_unrelated_phrase(self) -> None:
        session_id = uuid.uuid4()
        utt = FakeUtterance(uuid.uuid4(), 0, "The integral of sine is negative cosine")

        result = detect_cues(session_id, [utt])

        assert result.matches == []

    def test_patterns_load_from_config(self) -> None:
        patterns = load_cue_patterns()
        assert len(patterns) >= 5
        assert {p.id for p in patterns} >= {
            "moving_on",
            "next_topic",
            "completes_section",
            "break_reference",
        }


@pytest.mark.unit
class TestT344CueBoostsButDoesNotSplit:
    def test_cue_mid_topic_boosts_without_creating_new_segment(self) -> None:
        session_id = uuid.uuid4()
        patterns_by_id = {p.id: p for p in load_cue_patterns()}

        segment = FakeSegment(id=uuid.uuid4(), start_utt_seq=10, boundary_score=0.2)
        utt = FakeUtterance(uuid.uuid4(), 11, "Moving on to the next example within this topic")

        result = detect_cues(session_id, [utt])
        assert result.total_matches == 1

        boosts = apply_boundary_boosts(result.matches, [segment], patterns_by_id)

        assert len(boosts) == 1
        boost = boosts[0]
        assert boost.segment_id == segment.id
        assert boost.boosted_score > boost.original_score
        split_threshold = 1.5
        assert boost.boosted_score < split_threshold

    def test_cue_with_no_nearby_boundary_is_dropped(self) -> None:
        session_id = uuid.uuid4()
        patterns_by_id = {p.id: p for p in load_cue_patterns()}
        segment = FakeSegment(id=uuid.uuid4(), start_utt_seq=0, boundary_score=0.1)
        utt = FakeUtterance(uuid.uuid4(), 500, "Moving on to the next section")

        result = detect_cues(session_id, [utt])
        boosts = apply_boundary_boosts(
            result.matches, [segment], patterns_by_id, max_seq_distance=3
        )

        assert boosts == []

    def test_no_new_boundary_ids_introduced(self) -> None:
        """Boosts only ever reference existing segment ids — never create one."""
        session_id = uuid.uuid4()
        patterns_by_id = {p.id: p for p in load_cue_patterns()}
        segment = FakeSegment(id=uuid.uuid4(), start_utt_seq=5, boundary_score=0.3)
        utts = [
            FakeUtterance(uuid.uuid4(), 5, "That completes our review."),
            FakeUtterance(uuid.uuid4(), 6, "Next we'll look at proofs."),
        ]

        result = detect_cues(session_id, utts)
        boosts = apply_boundary_boosts(result.matches, [segment], patterns_by_id)

        assert {b.segment_id for b in boosts} <= {segment.id}


@pytest.mark.skip(reason=CORPUS_SKIP_REASON)
class TestT342T343HardGate:
    def test_precision_above_threshold_on_s05_corpus(self) -> None:
        raise NotImplementedError

    def test_pk_improves_over_s29_baseline(self) -> None:
        raise NotImplementedError
