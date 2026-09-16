"""FastAPI router - Subjects."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies.auth import get_current_user, get_db_session_with_rls
from src.api.dependencies.database import get_ddl_db_session
from src.api.dependencies.ownership import require_owned_subject
from src.api.schemas.subject import SubjectCreate, SubjectList, SubjectResponse, SubjectUpdate
from src.db.exceptions import DuplicateKeyError
from src.db.partitions.provisioner import PartitionProvisioner
from src.db.repositories.subject_repo import SubjectRepository

router = APIRouter(prefix="/subjects", tags=["subjects"])


@router.post("/", response_model=SubjectResponse, status_code=status.HTTP_201_CREATED)
async def create_subject(
    payload: SubjectCreate,
    db: AsyncSession = Depends(get_ddl_db_session),
    current_user: dict[str, object] = Depends(get_current_user),
) -> SubjectResponse:
    """Creates the subject row AND its per-subject table partitions
    (utterances/segments/etc. -- src/db/partitions/provisioner.py) in one
    transaction.

    Uses get_ddl_db_session (the superuser `lis` role), not the RLS-scoped
    get_db_session_with_rls (lis_app, gap #4): provisioning a partition is
    DDL (CREATE TABLE ... PARTITION OF ...), which requires owning the
    parent table -- lis_app intentionally has no DDL rights at all.
    Confirmed live: every subject created through this route before this
    fix had NO partition at all, so the very first utterance any real
    recording produced failed with "no partition of relation ... found
    for row" the moment transcription tried to persist it -- a universal
    bug blocking all real usage, not something narrow to one code path.
    """
    user_id = uuid.UUID(str(current_user["id"]))
    try:
        subject = await PartitionProvisioner().provision_subject(
            db, user_id, payload.name, payload.description
        )
    except DuplicateKeyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return SubjectResponse.model_validate(subject)


@router.get("/", response_model=SubjectList)
async def list_subjects(
    offset: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db_session_with_rls),
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
    db: AsyncSession = Depends(get_db_session_with_rls),
    current_user: dict[str, object] = Depends(get_current_user),
) -> SubjectResponse:
    subject = await require_owned_subject(subject_id, db, current_user)
    return SubjectResponse.model_validate(subject)


@router.patch("/{subject_id}", response_model=SubjectResponse)
async def update_subject(
    subject_id: uuid.UUID,
    payload: SubjectUpdate,
    db: AsyncSession = Depends(get_db_session_with_rls),
    current_user: dict[str, object] = Depends(get_current_user),
) -> SubjectResponse:
    subject = await require_owned_subject(subject_id, db, current_user)
    repo = SubjectRepository(db)
    subject = await repo.update(subject, name=payload.name, description=payload.description)
    return SubjectResponse.model_validate(subject)


@router.delete("/{subject_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_subject(
    subject_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session_with_rls),
    current_user: dict[str, object] = Depends(get_current_user),
) -> None:
    subject = await require_owned_subject(subject_id, db, current_user)
    repo = SubjectRepository(db)
    await repo.delete(subject)
