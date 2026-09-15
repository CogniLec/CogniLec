"""Subject CRUD endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies.auth import get_current_user_id
from src.api.dependencies.db import get_db
from src.api.schemas.session import SessionResponse
from src.api.schemas.subject import SubjectCreate, SubjectList, SubjectResponse, SubjectUpdate
from src.db.repositories.exceptions import DuplicateKeyError
from src.db.repositories.session_repo import SessionRepository
from src.db.repositories.subject_repo import SubjectRepository

router = APIRouter(prefix="/api/v1", tags=["subjects"])


@router.post("/subjects", response_model=SubjectResponse, status_code=status.HTTP_201_CREATED)
async def create_subject(
    data: SubjectCreate,
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> SubjectResponse:
    repo = SubjectRepository(db)
    try:
        subject = await repo.create(user_id, data)
    except DuplicateKeyError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return SubjectResponse.model_validate(subject)


@router.get("/subjects", response_model=SubjectList)
async def list_subjects(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> SubjectList:
    repo = SubjectRepository(db)
    items, total = await repo.list_by_user(user_id, offset, limit)
    return SubjectList(items=[SubjectResponse.model_validate(item) for item in items], total=total)


@router.get("/subjects/{subject_id}", response_model=SubjectResponse)
async def get_subject(
    subject_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> SubjectResponse:
    repo = SubjectRepository(db)
    subject = await repo.get_by_id(subject_id)
    if subject is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Subject not found")
    return SubjectResponse.model_validate(subject)


@router.patch("/subjects/{subject_id}", response_model=SubjectResponse)
async def update_subject(
    subject_id: UUID,
    data: SubjectUpdate,
    db: AsyncSession = Depends(get_db),
) -> SubjectResponse:
    repo = SubjectRepository(db)
    try:
        subject = await repo.update(subject_id, data)
    except DuplicateKeyError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    if subject is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Subject not found")
    return SubjectResponse.model_validate(subject)


@router.delete("/subjects/{subject_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_subject(
    subject_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    repo = SubjectRepository(db)
    deleted = await repo.delete(subject_id)
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Subject not found")


@router.get("/subjects/{subject_id}/sessions", response_model=list[SessionResponse])
async def list_subject_sessions(
    subject_id: UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> list[SessionResponse]:
    repo = SessionRepository(db)
    items, _total = await repo.list_by_subject(subject_id, offset, limit)
    return [SessionResponse.model_validate(item) for item in items]
