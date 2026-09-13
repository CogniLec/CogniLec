"""FastAPI router – Sessions."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies.database import get_db_session
from src.api.schemas.session import SessionCreate, SessionResponse, SessionUpdate
from src.db.exceptions import SessionNotFoundError
from src.db.repositories.session_repo import SessionRepository

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("/", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    payload: SessionCreate,
    db: AsyncSession = Depends(get_db_session),
) -> SessionResponse:
    repo = SessionRepository(db)
    session_obj = await repo.create(payload.subject_id, payload.session_type)
    return SessionResponse.model_validate(session_obj)


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
) -> SessionResponse:
    repo = SessionRepository(db)
    try:
        session_obj = await repo.get_or_raise(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SessionResponse.model_validate(session_obj)


@router.patch("/{session_id}", response_model=SessionResponse)
async def update_session(
    session_id: uuid.UUID,
    payload: SessionUpdate,
    db: AsyncSession = Depends(get_db_session),
) -> SessionResponse:
    repo = SessionRepository(db)
    try:
        session_obj = await repo.get_or_raise(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    session_obj = await repo.update_status(session_obj, payload.status)
    return SessionResponse.model_validate(session_obj)


@router.get("/by-subject/{subject_id}", response_model=list[SessionResponse])
async def list_sessions_by_subject(
    subject_id: uuid.UUID,
    offset: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db_session),
) -> list[SessionResponse]:
    repo = SessionRepository(db)
    sessions = await repo.list_for_subject(subject_id, offset=offset, limit=limit)
    return [SessionResponse.model_validate(s) for s in sessions]
