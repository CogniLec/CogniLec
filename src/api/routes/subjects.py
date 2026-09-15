"""FastAPI router - Subjects."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies.auth import get_current_user
from src.api.dependencies.database import get_db_session
from src.api.dependencies.ownership import require_owned_subject
from src.api.schemas.subject import SubjectCreate, SubjectList, SubjectResponse, SubjectUpdate
from src.db.exceptions import DuplicateKeyError
from src.db.repositories.subject_repo import SubjectRepository

router = APIRouter(prefix="/subjects", tags=["subjects"])


@router.post("/", response_model=SubjectResponse, status_code=status.HTTP_201_CREATED)
async def create_subject(
    payload: SubjectCreate,
    db: AsyncSession = Depends(get_db_session),
    current_user: dict[str, object] = Depends(get_current_user),
) -> SubjectResponse:
    user_id = uuid.UUID(str(current_user["id"]))
    repo = SubjectRepository(db)
    try:
        subject = await repo.create(user_id, payload.name, payload.description)
    except DuplicateKeyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return SubjectResponse.model_validate(subject)


@router.get("/", response_model=SubjectList)
async def list_subjects(
    offset: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db_session),
    current_user: dict[str, object] = Depends(get_current_user),
) -> SubjectList:
    user_id = uuid.UUID(str(current_user["id"]))
    repo = SubjectRepository(db)
    items = await repo.list_for_user(user_id, offset=offset, limit=limit)
    total = await repo.count_for_user(user_id)
    return SubjectList(
        items=[SubjectResponse.model_validate(s) for s in items],
        total=total,
    )


@router.get("/{subject_id}", response_model=SubjectResponse)
async def get_subject(
    subject_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
    current_user: dict[str, object] = Depends(get_current_user),
) -> SubjectResponse:
    subject = await require_owned_subject(subject_id, db, current_user)
    return SubjectResponse.model_validate(subject)


@router.patch("/{subject_id}", response_model=SubjectResponse)
async def update_subject(
    subject_id: uuid.UUID,
    payload: SubjectUpdate,
    db: AsyncSession = Depends(get_db_session),
    current_user: dict[str, object] = Depends(get_current_user),
) -> SubjectResponse:
    subject = await require_owned_subject(subject_id, db, current_user)
    repo = SubjectRepository(db)
    subject = await repo.update(subject, name=payload.name, description=payload.description)
    return SubjectResponse.model_validate(subject)


@router.delete("/{subject_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_subject(
    subject_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
    current_user: dict[str, object] = Depends(get_current_user),
) -> None:
    subject = await require_owned_subject(subject_id, db, current_user)
    repo = SubjectRepository(db)
    await repo.delete(subject)
