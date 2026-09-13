"""FastAPI router - Note read API (S46).

RLS-scoped (`get_db_session_with_rls`, S12): a session or topic belonging to
another user is invisible to the RLS policy, so a cross-user request 404s
rather than leaking existence (same convention as `transcript.py`, S24).
"""

from __future__ import annotations

import uuid
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies.auth import get_db_session_with_rls
from src.api.schemas.note import (
    ConsolidatedTopicNotesResponse,
    NoteSectionResponse,
    SessionNotesResponse,
)
from src.db.exceptions import SessionNotFoundError
from src.db.repositories.note_repo import NoteRepository
from src.db.repositories.session_repo import SessionRepository
from src.db.repositories.topic_repo import TopicRepository

router = APIRouter(tags=["notes"])


@router.get("/sessions/{session_id}/notes", response_model=SessionNotesResponse)
async def get_session_notes(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session_with_rls),
) -> SessionNotesResponse:
    session_repo = SessionRepository(db)
    try:
        session_obj = await session_repo.get_or_raise(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        ) from exc

    note_repo = NoteRepository(db)
    rows = await note_repo.get_sections_by_session(session_obj.subject_id, session_id)
    sections = []
    for row in rows:
        provenance = await note_repo.get_provenance_for_section(
            session_obj.subject_id, cast(Any, row)._mapping["id"]
        )
        sections.append(NoteSectionResponse.from_row(row, provenance))

    return SessionNotesResponse(
        session_id=session_id,
        subject_id=session_obj.subject_id,
        notes_ready=session_obj.notes_ready,
        sections=sections,
    )


@router.get(
    "/subjects/{subject_id}/topics/{topic_id}/notes",
    response_model=ConsolidatedTopicNotesResponse,
)
async def get_consolidated_topic_notes(
    subject_id: uuid.UUID,
    topic_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session_with_rls),
) -> ConsolidatedTopicNotesResponse:
    """FR-7.2: notes for a topic merged across every session containing it."""
    topic_repo = TopicRepository(db)
    topic = await topic_repo.get(subject_id, topic_id)
    if topic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Topic not found")

    note_repo = NoteRepository(db)
    rows = await note_repo.get_sections_by_topic(subject_id, topic_id)
    sections = []
    session_ids: list[uuid.UUID] = []
    for row in rows:
        mapping = cast(Any, row)._mapping
        if mapping["session_id"] not in session_ids:
            session_ids.append(mapping["session_id"])
        provenance = await note_repo.get_provenance_for_section(subject_id, mapping["id"])
        sections.append(NoteSectionResponse.from_row(row, provenance))

    return ConsolidatedTopicNotesResponse(
        topic_id=topic_id,
        subject_id=subject_id,
        session_ids=session_ids,
        sections=sections,
    )
