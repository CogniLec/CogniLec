"""FastAPI router - Sessions."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies.auth import get_current_user, get_db_session_with_rls
from src.api.dependencies.ownership import require_owned_session, require_owned_subject
from src.api.schemas.session import (
    ClassificationOverride,
    SessionCreate,
    SessionResponse,
    SessionUpdate,
)
from src.db.exceptions import DuplicateKeyError
from src.db.repositories.segment_repo import SegmentRepository
from src.db.repositories.session_repo import SessionRepository
from src.db.repositories.utterance_repo import UtteranceRepository
from src.ml.session_classifier import route_segments
from src.services.valkey_stream import ValkeyStreamProducer

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("/", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    payload: SessionCreate,
    db: AsyncSession = Depends(get_db_session_with_rls),
    current_user: dict[str, object] = Depends(get_current_user),
) -> SessionResponse:
    await require_owned_subject(payload.subject_id, db, current_user)
    repo = SessionRepository(db)
    try:
        session_obj = await repo.create(payload.subject_id, payload.session_type)
    except DuplicateKeyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return SessionResponse.model_validate(session_obj)


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session_with_rls),
    current_user: dict[str, object] = Depends(get_current_user),
) -> SessionResponse:
    session_obj = await require_owned_session(session_id, db, current_user)
    return SessionResponse.model_validate(session_obj)


@router.patch("/{session_id}", response_model=SessionResponse)
async def update_session(
    session_id: uuid.UUID,
    payload: SessionUpdate,
    db: AsyncSession = Depends(get_db_session_with_rls),
    current_user: dict[str, object] = Depends(get_current_user),
) -> SessionResponse:
    session_obj = await require_owned_session(session_id, db, current_user)
    repo = SessionRepository(db)
    session_obj = await repo.update_status(session_obj, payload.status)
    return SessionResponse.model_validate(session_obj)


@router.patch("/{session_id}/classification", response_model=SessionResponse)
async def override_classification(
    session_id: uuid.UUID,
    payload: ClassificationOverride,
    db: AsyncSession = Depends(get_db_session_with_rls),
    current_user: dict[str, object] = Depends(get_current_user),
) -> SessionResponse:
    """S35: operator post-hoc correction. Updates session_type, re-runs
    segment routing, and publishes `session.rerouted`."""
    session_obj = await require_owned_session(session_id, db, current_user)
    session_repo = SessionRepository(db)
    segment_repo = SegmentRepository(db)
    utterance_repo = UtteranceRepository(db)

    previous_type = session_obj.session_type
    segments = await segment_repo.get_by_session(session_obj.subject_id, session_id)
    utterances = await utterance_repo.get_by_session(session_obj.subject_id, session_id)
    utterance_by_id = {u.id: u for u in utterances}

    segment_texts: dict[uuid.UUID, str] = {}
    for segment in segments:
        start = utterance_by_id.get(segment.start_utt)
        end = utterance_by_id.get(segment.end_utt)
        if start is None or end is None:
            segment_texts[segment.id] = ""
            continue
        seg_utts = [u for u in utterances if start.seq <= u.seq <= end.seq]
        segment_texts[segment.id] = " ".join(u.text for u in seg_utts)

    await session_repo.update_classification(
        session_obj,
        session_type=payload.session_type,
        confidence=1.0,
        method="operator_override",
        details={"reason": payload.reason, "previous_type": previous_type},
    )

    route_plan = route_segments(session_id, payload.session_type, segment_texts)
    for route in route_plan.segment_routes:
        await segment_repo.update_route_target(route.segment_id, route.route_target)

    producer = ValkeyStreamProducer()
    try:
        await producer.publish_event(
            str(session_id),
            "session.rerouted",
            {
                "session_id": str(session_id),
                "previous_type": previous_type,
                "new_type": payload.session_type,
                "segments_moved": len(route_plan.segment_routes),
                "rerouted_at": datetime.now(UTC).isoformat(),
            },
        )
    finally:
        await producer.close()

    return SessionResponse.model_validate(session_obj)


@router.get("/by-subject/{subject_id}", response_model=list[SessionResponse])
async def list_sessions_by_subject(
    subject_id: uuid.UUID,
    offset: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db_session_with_rls),
    current_user: dict[str, object] = Depends(get_current_user),
) -> list[SessionResponse]:
    await require_owned_subject(subject_id, db, current_user)
    repo = SessionRepository(db)
    sessions = await repo.list_for_subject(subject_id, offset=offset, limit=limit)
    return [SessionResponse.model_validate(s) for s in sessions]
