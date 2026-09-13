"""S63 — `image_generation_cache` persistence."""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.services.image_generation.cache import concept_hash


class GenerationCacheRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, subject_id: uuid.UUID, concept_description: str) -> uuid.UUID | None:
        result = await self._session.scalar(
            text(
                "SELECT generated_image_id FROM image_generation_cache "
                "WHERE subject_id = :subject_id AND concept_hash = :hash"
            ),
            {"subject_id": subject_id, "hash": concept_hash(concept_description)},
        )
        return result if result is None else uuid.UUID(str(result))

    async def put(
        self, subject_id: uuid.UUID, concept_description: str, generated_image_id: uuid.UUID
    ) -> None:
        await self._session.execute(
            text(
                """
                INSERT INTO image_generation_cache (subject_id, concept_hash, generated_image_id)
                VALUES (:subject_id, :hash, :generated_image_id)
                ON CONFLICT (subject_id, concept_hash) DO NOTHING
                """
            ),
            {
                "subject_id": subject_id,
                "hash": concept_hash(concept_description),
                "generated_image_id": generated_image_id,
            },
        )
        await self._session.flush()
