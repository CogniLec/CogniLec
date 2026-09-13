"""Note repository."""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class NoteRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_section(
        self, subject_id: uuid.UUID, data: dict[str, object]
    ) -> dict[str, uuid.UUID]:
        """Create a note section."""
        result = await self._session.execute(
            text("""
                INSERT INTO note_sections (subject_id, topic_id, session_id, heading, body_md,
                                          depth, ordinal, model_version)
                VALUES (:subject_id, :topic_id, :session_id, :heading, :body_md,
                        :depth, :ordinal, :model_version)
                RETURNING id
            """),
            {"subject_id": subject_id, **data},
        )
        await self._session.flush()
        row = result.fetchone()
        return {"id": row[0]} if row else {}

    async def create_provenance(
        self, subject_id: uuid.UUID, note_section_id: uuid.UUID, utterance_ids: list[uuid.UUID]
    ) -> int:
        """Create provenance links."""
        for uid in utterance_ids:
            await self._session.execute(
                text("""
                    INSERT INTO note_provenance (subject_id, note_section_id, utterance_id)
                    VALUES (:subject_id, :note_section_id, :utterance_id)
                """),
                {"subject_id": subject_id, "note_section_id": note_section_id, "utterance_id": uid},
            )
        await self._session.flush()
        return len(utterance_ids)

    async def create_asset(
        self, subject_id: uuid.UUID, data: dict[str, object]
    ) -> dict[str, uuid.UUID]:
        """Create a note asset."""
        result = await self._session.execute(
            text("""
                INSERT INTO note_assets (subject_id, note_section_id, asset_type, object_key,
                                         source_url, licence, match_score, is_ai_generated,
                                         ocr_text, ocr_confidence)
                VALUES (:subject_id, :note_section_id, :asset_type, :object_key,
                        :source_url, :licence, :match_score, :is_ai_generated,
                        :ocr_text, :ocr_confidence)
                RETURNING id
            """),
            {"subject_id": subject_id, **data},
        )
        await self._session.flush()
        row = result.fetchone()
        return {"id": row[0]} if row else {}

    async def get_sections_by_session(
        self, subject_id: uuid.UUID, session_id: uuid.UUID
    ) -> list[object]:
        """Get note sections for a session."""
        result = await self._session.execute(
            text("""
                SELECT * FROM note_sections
                WHERE subject_id = :subject_id AND session_id = :session_id
                ORDER BY ordinal
            """),
            {"subject_id": str(subject_id), "session_id": str(session_id)},
        )
        return list(result.fetchall())

    async def get_sections_by_topic(
        self, subject_id: uuid.UUID, topic_id: uuid.UUID
    ) -> list[object]:
        """S46 T46.2: all sections across every session sharing this topic,

        merged into consolidated topic notes (FR-7.2).
        """
        result = await self._session.execute(
            text("""
                SELECT * FROM note_sections
                WHERE subject_id = :subject_id AND topic_id = :topic_id
                ORDER BY session_id, ordinal
            """),
            {"subject_id": str(subject_id), "topic_id": str(topic_id)},
        )
        return list(result.fetchall())

    async def get_provenance_for_section(
        self, subject_id: uuid.UUID, note_section_id: uuid.UUID
    ) -> list[uuid.UUID]:
        """Utterance IDs backing one note section (S46 provenance navigation)."""
        result = await self._session.execute(
            text("""
                SELECT utterance_id FROM note_provenance
                WHERE subject_id = :subject_id AND note_section_id = :note_section_id
            """),
            {"subject_id": str(subject_id), "note_section_id": str(note_section_id)},
        )
        return [row[0] for row in result.fetchall()]

    async def get_assets(self, note_section_id: uuid.UUID) -> list[object]:
        """Get assets for a note section."""
        result = await self._session.execute(
            text("""
                SELECT * FROM note_assets
                WHERE note_section_id = :note_section_id
            """),
            {"note_section_id": str(note_section_id)},
        )
        return list(result.fetchall())
