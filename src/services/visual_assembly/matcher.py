"""S64 — board photo matching by timestamp proximity or semantic similarity (FR-4.17)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from src.services.visual_assembly.models import (
    DEFAULT_SEMANTIC_SIMILARITY_THRESHOLD,
    DEFAULT_TIMESTAMP_THRESHOLD_SECONDS,
    BoardPhotoMatch,
)


@dataclass(frozen=True)
class UploadTimestamp:
    upload_id: uuid.UUID
    captured_at_seconds: int


@dataclass(frozen=True)
class SegmentWindow:
    note_section_id: uuid.UUID
    start_seconds: int
    end_seconds: int


def match_by_timestamp(
    upload: UploadTimestamp,
    windows: list[SegmentWindow],
    threshold_seconds: int = DEFAULT_TIMESTAMP_THRESHOLD_SECONDS,
) -> BoardPhotoMatch | None:
    """Match to the window whose range is closest to the upload's timestamp."""
    best: BoardPhotoMatch | None = None
    best_delta = threshold_seconds + 1
    for window in windows:
        if window.start_seconds <= upload.captured_at_seconds <= window.end_seconds:
            delta = 0
        else:
            delta = min(
                abs(upload.captured_at_seconds - window.start_seconds),
                abs(upload.captured_at_seconds - window.end_seconds),
            )
        if delta <= threshold_seconds and delta < best_delta:
            best_delta = delta
            best = BoardPhotoMatch(
                upload_id=upload.upload_id,
                note_section_id=window.note_section_id,
                match_method="timestamp",
                match_confidence=max(0.0, 1.0 - delta / (threshold_seconds or 1)),
                timestamp_delta_seconds=delta,
            )
    return best


def match_by_semantic(
    upload_id: uuid.UUID,
    similarities: list[tuple[uuid.UUID, float]],
    threshold: float = DEFAULT_SEMANTIC_SIMILARITY_THRESHOLD,
) -> BoardPhotoMatch | None:
    """`similarities` is a list of (note_section_id, cosine_similarity) pairs."""
    best: tuple[uuid.UUID, float] | None = None
    for section_id, sim in similarities:
        if sim >= threshold and (best is None or sim > best[1]):
            best = (section_id, sim)
    if best is None:
        return None
    return BoardPhotoMatch(
        upload_id=upload_id,
        note_section_id=best[0],
        match_method="semantic",
        match_confidence=best[1],
        semantic_similarity=best[1],
    )


def match_board_photo(
    upload: UploadTimestamp,
    windows: list[SegmentWindow],
    similarities: list[tuple[uuid.UUID, float]],
    threshold_seconds: int = DEFAULT_TIMESTAMP_THRESHOLD_SECONDS,
    similarity_threshold: float = DEFAULT_SEMANTIC_SIMILARITY_THRESHOLD,
) -> BoardPhotoMatch | None:
    """Timestamp first, semantic fallback, per the S64 fallback instructions."""
    match = match_by_timestamp(upload, windows, threshold_seconds)
    if match is not None:
        return match
    return match_by_semantic(upload.upload_id, similarities, similarity_threshold)
