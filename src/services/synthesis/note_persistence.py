"""S45 — Task T5: idempotent note persistence + FR-5.6 guard.

Sections upsert on `(session_id, topic_id, ordinal)`: re-running the flow
after a partial or full completion updates existing rows in place rather
than duplicating them (NFR-R6). `topic_id` is nullable, so the "existing
row" lookup uses `IS NOT DISTINCT FROM` rather than `=` (plain `=` never
matches NULL against NULL in SQL, which would break idempotency for
sections with no topic assignment).

FR-5.6: a note section citing an utterance ID that isn't a real, persisted
DB-1 row for that `(subject_id, session_id)` is rejected outright - no
section is ever written whose provenance can't be resolved.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.models.session import Session, SessionStatus
from src.db.models.utterance import Utterance
from src.services.synthesis.note_synthesis import NoteSectionOutput


class NoteWriteRejectedError(Exception):
    """FR-5.6: raised when a section cites utterances with no DB-1 record."""


async def _existing_utterance_ids(
    db: AsyncSession, subject_id: uuid.UUID, session_id: uuid.UUID
) -> set[str]:
    stmt = select(Utterance.id).where(
        Utterance.subject_id == subject_id, Utterance.session_id == session_id
    )
    result = await db.execute(stmt)
    return {str(row[0]) for row in result.all()}


async def _find_existing_section_id(
    db: AsyncSession,
    subject_id: uuid.UUID,
    session_id: uuid.UUID,
    topic_id: uuid.UUID | None,
    ordinal: int,
) -> uuid.UUID | None:
    result = await db.execute(
        text("""
            SELECT id FROM note_sections
            WHERE subject_id = :subject_id AND session_id = :session_id
              AND topic_id IS NOT DISTINCT FROM :topic_id AND ordinal = :ordinal
        """),
        {
            "subject_id": subject_id,
            "session_id": session_id,
            "topic_id": topic_id,
            "ordinal": ordinal,
        },
    )
    row = result.fetchone()
    return row[0] if row else None


async def persist_note_sections(
    db: AsyncSession,
    subject_id: uuid.UUID,
    session_id: uuid.UUID,
    topic_id: uuid.UUID | None,
    sections: list[NoteSectionOutput],
    model_version: str | None = None,
    embeddings_by_ordinal: dict[int, list[float]] | None = None,
) -> list[uuid.UUID]:
    """Idempotently upsert sections + provenance. Raises without writing anything

    if any section cites an utterance absent from DB-1 (FR-5.6) - validated
    up front so a partial write never happens.
    """
    known_ids = await _existing_utterance_ids(db, subject_id, session_id)
    for section in sections:
        missing = set(section.source_utt_ids) - known_ids
        if missing:
            msg = f"section {section.heading!r} cites utterances with no DB-1 record: {missing}"
            raise NoteWriteRejectedError(msg)

    section_ids: list[uuid.UUID] = []
    for section in sections:
        existing_id = await _find_existing_section_id(
            db, subject_id, session_id, topic_id, section.ordinal
        )
        if existing_id is not None:
            await db.execute(
                text("""
                    UPDATE note_sections
                    SET heading = :heading, body_md = :body_md, depth = :depth,
                        model_version = :model_version, updated_at = now()
                    WHERE subject_id = :subject_id AND id = :id
                """),
                {
                    "subject_id": subject_id,
                    "id": existing_id,
                    "heading": section.heading,
                    "body_md": section.body_md,
                    "depth": section.depth,
                    "model_version": model_version,
                },
            )
            await db.execute(
                text("""
                    DELETE FROM note_provenance
                    WHERE subject_id = :subject_id AND note_section_id = :sid
                """),
                {"subject_id": subject_id, "sid": existing_id},
            )
            section_id = existing_id
        else:
            result = await db.execute(
                text("""
                    INSERT INTO note_sections
                        (subject_id, topic_id, session_id, heading, body_md,
                         depth, ordinal, model_version)
                    VALUES
                        (:subject_id, :topic_id, :session_id, :heading, :body_md,
                         :depth, :ordinal, :model_version)
                    RETURNING id
                """),
                {
                    "subject_id": subject_id,
                    "topic_id": topic_id,
                    "session_id": session_id,
                    "heading": section.heading,
                    "body_md": section.body_md,
                    "depth": section.depth,
                    "ordinal": section.ordinal,
                    "model_version": model_version,
                },
            )
            section_id = result.fetchone()[0]  # type: ignore[index]

        for utt_id in section.source_utt_ids:
            await db.execute(
                text("""
                    INSERT INTO note_provenance (subject_id, note_section_id, utterance_id)
                    VALUES (:subject_id, :note_section_id, :utterance_id)
                """),
                {"subject_id": subject_id, "note_section_id": section_id, "utterance_id": utt_id},
            )
        embedding = (embeddings_by_ordinal or {}).get(section.ordinal)
        if embedding is not None:
            await db.execute(
                text("""
                    UPDATE note_sections SET embedding = :embedding
                    WHERE subject_id = :subject_id AND id = :id
                """),
                {"subject_id": subject_id, "id": section_id, "embedding": str(embedding)},
            )

        section_ids.append(section_id)

    await db.flush()
    return section_ids


async def mark_notes_ready(db: AsyncSession, session_obj: Session) -> Session:
    """Flip a session to complete/notes_ready=true. Call only after a

    successful `persist_note_sections` commit (T45.5) - never speculatively.
    """
    session_obj.notes_ready = True
    session_obj.status = SessionStatus.COMPLETE
    await db.flush()
    return session_obj
