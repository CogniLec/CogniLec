"""FastAPI router - transcript read API (S24).

RLS-scoped: this router's `db` dependency is `get_db_session_with_rls`, which
sets `app.user_id` before any query runs. A session belonging to another
user is simply invisible to the RLS policy (S12), so `SessionRepository`
sees no row and this returns 404 - never 403 - avoiding an existence leak.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies.auth import get_db_session_with_rls
from src.api.schemas.transcript import TranscriptResponse, TranscriptUtterance
from src.db.exceptions import SessionNotFoundError
from src.db.repositories.session_repo import SessionRepository
from src.db.repositories.utterance_repo import UtteranceRepository

router = APIRouter(prefix="/sessions", tags=["transcript"])

MAX_LIMIT = 200


@router.get("/{session_id}/transcript", response_model=TranscriptResponse)
async def get_transcript(
    session_id: uuid.UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=MAX_LIMIT),
    include_filtered: bool = False,
    speaker_tag: str | None = None,
    search: str | None = None,
    db: AsyncSession = Depends(get_db_session_with_rls),
) -> TranscriptResponse:
    session_repo = SessionRepository(db)
    try:
        session_obj = await session_repo.get_or_raise(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        ) from exc

    utterance_repo = UtteranceRepository(db)
    utterances, total = await utterance_repo.get_transcript_page(
        subject_id=session_obj.subject_id,
        session_id=session_id,
        offset=offset,
        limit=limit,
        include_filtered=include_filtered,
        speaker_tag=speaker_tag,
        search=search,
    )
    filtered_count = await utterance_repo.count_filtered(session_obj.subject_id, session_id)

    return TranscriptResponse(
        session_id=session_id,
        subject_id=session_obj.subject_id,
        total_utterances=total,
        filtered_count=filtered_count,
        offset=offset,
        limit=limit,
        utterances=[TranscriptUtterance.from_model(u) for u in utterances],
        audio_url=None,
        session_status=session_obj.status,
        notes_ready=session_obj.notes_ready,
    )
