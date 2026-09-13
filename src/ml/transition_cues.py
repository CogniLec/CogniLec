"""S34 — Transition cue detection: a second, independent boundary signal.

Cues BOOST existing S28 `segments.boundary_score` values; they never create
new boundaries (§6.3 "boosts, not overrides" invariant).
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

import yaml
from pydantic import BaseModel

log = logging.getLogger(__name__)

TRANSITION_CUES_CONFIG_PATH = Path("config/transition_cues.yaml")
BOOST_MULTIPLIER_DEFAULT = 0.2


class CuePattern(BaseModel):
    id: str
    pattern: str
    language: str
    category: str
    weight: float


class CueMatch(BaseModel):
    utterance_id: uuid.UUID
    seq: int
    pattern_id: str
    matched_text: str
    position_start: int
    position_end: int


class TransitionCueResult(BaseModel):
    session_id: uuid.UUID
    matches: list[CueMatch]
    total_matches: int
    detected_at: datetime


class BoundaryBoost(BaseModel):
    segment_id: uuid.UUID
    original_score: float
    boosted_score: float
    cue_count: int
    patterns_matched: list[str]


class UtteranceLike(Protocol):
    id: uuid.UUID
    seq: int
    text: str


class SegmentLike(Protocol):
    id: uuid.UUID
    start_utt_seq: int
    boundary_score: float | None


@lru_cache(maxsize=1)
def load_cue_patterns(path: str = str(TRANSITION_CUES_CONFIG_PATH)) -> list[CuePattern]:
    raw: dict[str, Any] = yaml.safe_load(Path(path).read_text())
    return [CuePattern(**entry) for entry in raw.get("cues", [])]


def detect_cues(
    session_id: uuid.UUID,
    utterances: Sequence[UtteranceLike],
    config_path: str = str(TRANSITION_CUES_CONFIG_PATH),
) -> TransitionCueResult:
    """Pattern-matching phase (§6.2 step 1). Pure, DB-free."""
    patterns = load_cue_patterns(config_path)
    compiled = [(p, re.compile(p.pattern, re.IGNORECASE)) for p in patterns]

    matches: list[CueMatch] = []
    for utt in utterances:
        for pattern, regex in compiled:
            for m in regex.finditer(utt.text):
                matches.append(
                    CueMatch(
                        utterance_id=utt.id,
                        seq=utt.seq,
                        pattern_id=pattern.id,
                        matched_text=m.group(0),
                        position_start=m.start(),
                        position_end=m.end(),
                    )
                )

    return TransitionCueResult(
        session_id=session_id,
        matches=matches,
        total_matches=len(matches),
        detected_at=datetime.now(UTC),
    )


LLMConfirmFn = Callable[[list[CueMatch]], Awaitable[set[str]]]
"""Given cue matches, returns the set of match keys (f"{utterance_id}:{pattern_id}")
confirmed as genuine transitions. May raise on failure — callers fall back to
pattern-only boosting per §6.2 step 2 failure handling."""


async def confirm_cues_with_llm(
    matches: list[CueMatch],
    confirm_fn: LLMConfirmFn | None,
    max_candidates_per_call: int = 20,
) -> list[CueMatch]:
    """LLM confirmation phase. Falls back to pattern-only (all matches confirmed)
    if `confirm_fn` is None or raises, per §6.2 failure handling."""
    if confirm_fn is None or not matches:
        return matches

    confirmed: list[CueMatch] = []
    try:
        for i in range(0, len(matches), max_candidates_per_call):
            batch = matches[i : i + max_candidates_per_call]
            confirmed_keys = await confirm_fn(batch)
            confirmed.extend(
                m for m in batch if f"{m.utterance_id}:{m.pattern_id}" in confirmed_keys
            )
    except Exception:
        log.warning("cue_llm_fallback", exc_info=True)
        return matches
    else:
        return confirmed


def apply_boundary_boosts(
    matches: list[CueMatch],
    segments: Sequence[SegmentLike],
    patterns_by_id: dict[str, CuePattern],
    boost_multiplier: float = BOOST_MULTIPLIER_DEFAULT,
    max_seq_distance: int = 3,
) -> list[BoundaryBoost]:
    """Score boosting phase (§6.2 step 3). Boosts existing boundary scores only —
    never creates a new segment. A cue with no nearby S28 boundary is dropped
    (logged, per §6.3)."""
    boosts: list[BoundaryBoost] = []
    matches_by_segment: dict[uuid.UUID, list[CueMatch]] = {}

    sorted_segments = sorted(segments, key=lambda s: s.start_utt_seq)
    for match in matches:
        nearest = None
        nearest_distance = None
        for seg in sorted_segments:
            distance = abs(seg.start_utt_seq - match.seq)
            if nearest_distance is None or distance < nearest_distance:
                nearest, nearest_distance = seg, distance
        if nearest is None or nearest_distance is None or nearest_distance > max_seq_distance:
            log.debug("cue_no_nearby_boundary", extra={"seq": match.seq})
            continue
        matches_by_segment.setdefault(nearest.id, []).append(match)

    segments_by_id = {s.id: s for s in segments}
    for segment_id, seg_matches in matches_by_segment.items():
        segment = segments_by_id[segment_id]
        original_score = segment.boundary_score or 0.0
        total_weight = sum(patterns_by_id[m.pattern_id].weight for m in seg_matches)
        boosted_score = original_score + (total_weight * boost_multiplier)
        boosts.append(
            BoundaryBoost(
                segment_id=segment_id,
                original_score=original_score,
                boosted_score=boosted_score,
                cue_count=len(seg_matches),
                patterns_matched=[m.pattern_id for m in seg_matches],
            )
        )

    return boosts
