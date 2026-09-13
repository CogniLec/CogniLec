"""S52 — coverage query, recompute-trigger, and user-correction endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies.database import get_db_session, get_syllabus_db_session
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
    main_db: AsyncSession = Depends(get_db_session),
) -> SyllabusCoverageSummary:
    return await _service(syllabus_db, main_db).get_summary(subject_id)


@router.post("/{subject_id}/coverage/update", status_code=status.HTTP_202_ACCEPTED)
async def trigger_coverage_update(
    subject_id: uuid.UUID,
    session_id: uuid.UUID | None = None,
    syllabus_db: AsyncSession = Depends(get_syllabus_db_session),
    main_db: AsyncSession = Depends(get_db_session),
) -> SyllabusCoverageSummary:
    service = _service(syllabus_db, main_db)
    if session_id is not None:
        return await service.post_session_update(subject_id, session_id)
    return await service.recompute_coverage(subject_id)


@router.post("/{subject_id}/coverage/correct")
async def correct_alignment(
    subject_id: uuid.UUID,
    correction: AlignmentCorrection,
    syllabus_db: AsyncSession = Depends(get_syllabus_db_session),
) -> dict[str, str]:
    repo = CoverageRepository(syllabus_db)
    await repo.persist_user_correction(subject_id, correction)
    return {"status": "applied"}
