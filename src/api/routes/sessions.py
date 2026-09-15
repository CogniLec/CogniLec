"""Session CRUD + status-transition endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies.db import get_db
from src.api.schemas.session import SessionCreate, SessionResponse, SessionStatusUpdate
from src.db.repositories.exceptions import InvalidStatusTransitionError, SessionNotFoundError
from src.db.repositories.session_repo import SessionRepository

router = APIRouter(prefix="/api/v1", tags=["sessions"])


@router.post("/sessions", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    data: SessionCreate,
    db: AsyncSession = Depends(get_db),
) -> SessionResponse:
    repo = SessionRepository(db)
    session = await repo.create(data.subject_id, data.session_type)
    return SessionResponse.model_validate(session)


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> SessionResponse:
    repo = SessionRepository(db)
    session = await repo.get_by_id(session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    return SessionResponse.model_validate(session)


@router.patch("/sessions/{session_id}", response_model=SessionResponse)
async def update_session_status(
    session_id: UUID,
    data: SessionStatusUpdate,
    db: AsyncSession = Depends(get_db),
) -> SessionResponse:
    repo = SessionRepository(db)
    try:
        session = await repo.update_status(session_id, data.status)
    except SessionNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except InvalidStatusTransitionError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return SessionResponse.model_validate(session)
