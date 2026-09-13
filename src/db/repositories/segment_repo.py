"""Segment repository."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.segment import Segment

if TYPE_CHECKING:
    from src.ml.clustering.segmentation import SegmentationResult


class SegmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def bulk_insert(self, subject_id: uuid.UUID, segments: list[dict[str, object]]) -> int:
        """Insert segments in bulk."""
        if not segments:
            return 0

        for seg in segments:
            seg["subject_id"] = subject_id

        await self._session.execute(
            text("""
                INSERT INTO segments (subject_id, session_id, start_utt, end_utt,
                                     topic_id, boundary_score, confidence)
                VALUES (:subject_id, :session_id, :start_utt, :end_utt,
                        :topic_id, :boundary_score, :confidence)
            """),
            segments,
        )
        await self._session.flush()
        return len(segments)

    async def persist_segments(
        self, subject_id: uuid.UUID, session_id: uuid.UUID, result: SegmentationResult
    ) -> int:
        """S28 §5.3: bulk-persist a `SegmentationResult` to the `segments` table."""
        rows: list[dict[str, object]] = [
            {
                "session_id": session_id,
                "start_utt": seg.start_utt_id,
                "end_utt": seg.end_utt_id,
                "topic_id": None,
                "boundary_score": seg.boundary_score,
                "confidence": seg.confidence,
            }
            for seg in result.segments
        ]
        return await self.bulk_insert(subject_id, rows)

    async def update_route_target(self, segment_id: uuid.UUID, route_target: str) -> None:
        """S35: persist a segment's routing decision."""
        await self._session.execute(
            text("UPDATE segments SET route_target = :route_target WHERE id = :id"),
            {"route_target": route_target, "id": segment_id},
        )
        await self._session.flush()

    async def get_by_session(self, subject_id: uuid.UUID, session_id: uuid.UUID) -> list[Segment]:
        """Get segments for a session."""
        result = await self._session.execute(
            select(Segment)
            .where(Segment.subject_id == subject_id, Segment.session_id == session_id)
            .order_by(Segment.created_at)
        )
        return list(result.scalars().all())
