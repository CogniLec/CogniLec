"""Topic repository (S30/S31/S32)."""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.topic import Topic


class TopicRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        subject_id: uuid.UUID,
        session_id: uuid.UUID | None,
        centroid: list[float],
        label: str | None = None,
        keywords: list[str] | None = None,
        keyword_scores: list[float] | None = None,
        segment_count: int = 0,
        utterance_count: int = 0,
    ) -> Topic:
        topic = Topic(
            subject_id=subject_id,
            session_id=session_id,
            centroid=centroid,
            label=label,
            keywords=keywords,
            keyword_scores=keyword_scores,
            segment_count=segment_count,
            utterance_count=utterance_count,
        )
        self._session.add(topic)
        await self._session.flush()
        return topic

    async def get(self, subject_id: uuid.UUID, topic_id: uuid.UUID) -> Topic | None:
        return await self._session.get(Topic, (subject_id, topic_id))

    async def list_for_subject(self, subject_id: uuid.UUID) -> list[Topic]:
        from sqlalchemy import select

        result = await self._session.execute(
            select(Topic).where(Topic.subject_id == subject_id).order_by(Topic.created_at)
        )
        return list(result.scalars().all())

    async def nearest_centroid(
        self, subject_id: uuid.UUID, embedding: list[float]
    ) -> tuple[uuid.UUID, float] | None:
        """S32: nearest existing topic centroid by cosine distance, scoped to subject_id."""
        result = await self._session.execute(
            text("""
                SELECT id, centroid <=> :embedding AS distance
                FROM topics WHERE subject_id = :subject_id
                ORDER BY distance ASC LIMIT 1
            """),
            {"subject_id": str(subject_id), "embedding": str(embedding)},
        )
        row = result.mappings().first()
        if row is None:
            return None
        return uuid.UUID(str(row["id"])), float(row["distance"])

    async def update_centroid(
        self,
        subject_id: uuid.UUID,
        topic_id: uuid.UUID,
        new_centroid: list[float],
        increment: int = 1,
    ) -> None:
        await self._session.execute(
            text("""
                UPDATE topics
                SET centroid = :centroid, segment_count = segment_count + :increment,
                    updated_at = now()
                WHERE subject_id = :subject_id AND id = :id
            """),
            {
                "subject_id": str(subject_id),
                "id": str(topic_id),
                "centroid": str(new_centroid),
                "increment": increment,
            },
        )
        await self._session.flush()

    async def update_label(
        self, subject_id: uuid.UUID, topic_id: uuid.UUID, label: str, is_user_edited: bool = True
    ) -> None:
        await self._session.execute(
            text("""
                UPDATE topics
                SET label = :label, is_user_edited = :is_user_edited, updated_at = now()
                WHERE subject_id = :subject_id AND id = :id
            """),
            {
                "subject_id": str(subject_id),
                "id": str(topic_id),
                "label": label,
                "is_user_edited": is_user_edited,
            },
        )
        await self._session.flush()

    async def update_keywords(
        self,
        subject_id: uuid.UUID,
        topic_id: uuid.UUID,
        keywords: list[str],
        keyword_scores: list[float],
    ) -> None:
        await self._session.execute(
            text("""
                UPDATE topics SET keywords = :keywords, keyword_scores = :scores, updated_at = now()
                WHERE subject_id = :subject_id AND id = :id
            """),
            {
                "subject_id": str(subject_id),
                "id": str(topic_id),
                "keywords": keywords,
                "scores": keyword_scores,
            },
        )
        await self._session.flush()
