"""S52 — coverage query, recompute-trigger, and user-correction endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies.auth import get_current_user, get_db_session_with_rls
from src.api.dependencies.database import get_syllabus_db_session
from src.api.dependencies.ownership import require_owned_subject
from src.db.repositories.coverage_repo import CoverageRepository
from src.services.coverage.coverage_service import CoverageService
from src.services.coverage.models import AlignmentCorrection, SyllabusCoverageSummary

router = APIRouter(prefix="/subjects", tags=["coverage"])


def _service(syllabus_db: AsyncSession, main_db: AsyncSession) -> CoverageService:
    return CoverageService(CoverageRepository(syllabus_db, main_db))


@router.get("/{subject_id}/coverage", response_model=SyllabusCoverageSummary)
async def get_coverage(
    subject_id: uuid.UUID,
    syllabus_db: AsyncSession = Depends(get_syllabus_db_session),
    main_db: AsyncSession = Depends(get_db_session_with_rls),
    current_user: dict[str, object] = Depends(get_current_user),
) -> SyllabusCoverageSummary:
    await require_owned_subject(subject_id, main_db, current_user)
    return await _service(syllabus_db, main_db).get_summary(subject_id)


@router.post("/{subject_id}/coverage/update", status_code=status.HTTP_202_ACCEPTED)
async def trigger_coverage_update(
    subject_id: uuid.UUID,
    session_id: uuid.UUID | None = None,
    syllabus_db: AsyncSession = Depends(get_syllabus_db_session),
    main_db: AsyncSession = Depends(get_db_session_with_rls),
    current_user: dict[str, object] = Depends(get_current_user),
) -> SyllabusCoverageSummary:
    await require_owned_subject(subject_id, main_db, current_user)
    service = _service(syllabus_db, main_db)
    if session_id is not None:
        return await service.post_session_update(subject_id, session_id)
    return await service.recompute_coverage(subject_id)


@router.post("/{subject_id}/coverage/correct")
async def correct_alignment(
    subject_id: uuid.UUID,
    correction: AlignmentCorrection,
    syllabus_db: AsyncSession = Depends(get_syllabus_db_session),
    main_db: AsyncSession = Depends(get_db_session_with_rls),
    current_user: dict[str, object] = Depends(get_current_user),
) -> dict[str, str]:
    await require_owned_subject(subject_id, main_db, current_user)
    repo = CoverageRepository(syllabus_db)
    await repo.persist_user_correction(subject_id, correction)
    return {"status": "applied"}
