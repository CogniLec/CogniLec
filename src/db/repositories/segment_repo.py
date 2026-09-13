"""Segment repository."""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.segment import Segment


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

    async def get_by_session(self, subject_id: uuid.UUID, session_id: uuid.UUID) -> list[Segment]:
        """Get segments for a session."""
        result = await self._session.execute(
            text("""
                SELECT * FROM segments
                WHERE subject_id = :subject_id AND session_id = :session_id
                ORDER BY created_at
            """),
            {"subject_id": str(subject_id), "session_id": str(session_id)},
        )
        return list(result.scalars().all())
