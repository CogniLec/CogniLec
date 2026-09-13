"""S28 — custom TextTiling-style boundary detection over windowed embeddings."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

import numpy as np


class _HasId(Protocol):
    id: uuid.UUID


@dataclass
class SegmentResult:
    """A detected segment within a session (S28 §5.2)."""

    start_utt_id: uuid.UUID
    end_utt_id: uuid.UUID
    start_idx: int
    end_idx: int
    boundary_score: float
    confidence: float


@dataclass
class SegmentationResult:
    session_id: uuid.UUID | None
    segments: list[SegmentResult]
    num_segments: int
    similarity_scores: list[float]


_Vec = np.ndarray[object, np.dtype[np.float64]]


def _cosine(a: _Vec, b: _Vec) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 1.0
    return float(np.dot(a, b) / denom)


def segment_session(
    utterances: list[_HasId],
    embeddings: list[list[float]],
    threshold_percentile: float = 25.0,
    session_id: uuid.UUID | None = None,
) -> SegmentationResult:
    """Segment a session using adaptive TextTiling over windowed embeddings (S28 §5.2/§6.1).

    Adjacent-window cosine similarities are computed; boundaries are placed
    where the similarity falls below the `threshold_percentile` of the
    session's own similarity distribution. Segments are ordered, contiguous
    and non-overlapping - every utterance belongs to exactly one segment.
    """
    n = len(utterances)
    if len(embeddings) != n:
        msg = f"embeddings length {len(embeddings)} != utterances length {n}"
        raise ValueError(msg)

    if n == 0:
        return SegmentationResult(
            session_id=session_id, segments=[], num_segments=0, similarity_scores=[]
        )

    if n == 1:
        seg = SegmentResult(
            start_utt_id=utterances[0].id,
            end_utt_id=utterances[0].id,
            start_idx=0,
            end_idx=0,
            boundary_score=1.0,
            confidence=1.0,
        )
        return SegmentationResult(
            session_id=session_id, segments=[seg], num_segments=1, similarity_scores=[]
        )

    arr = np.array(embeddings, dtype=float)
    similarities = [_cosine(arr[i], arr[i + 1]) for i in range(n - 1)]

    threshold = float(np.percentile(similarities, threshold_percentile))
    boundaries = [i for i, s in enumerate(similarities) if s < threshold]

    spread = float(np.std(similarities))

    segments: list[SegmentResult] = []
    start = 0
    for b in boundaries:
        score = similarities[b]
        confidence = min(1.0, abs(threshold - score) / spread) if spread > 0 else 0.5
        segments.append(
            SegmentResult(
                start_utt_id=utterances[start].id,
                end_utt_id=utterances[b].id,
                start_idx=start,
                end_idx=b,
                boundary_score=score,
                confidence=confidence,
            )
        )
        start = b + 1

    segments.append(
        SegmentResult(
            start_utt_id=utterances[start].id,
            end_utt_id=utterances[n - 1].id,
            start_idx=start,
            end_idx=n - 1,
            boundary_score=1.0,
            confidence=1.0,
        )
    )

    return SegmentationResult(
        session_id=session_id,
        segments=segments,
        num_segments=len(segments),
        similarity_scores=similarities,
    )
