"""S53 — syllabus seeding status endpoint."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies.database import get_syllabus_db_session
from src.db.repositories.syllabus_repo import SyllabusRepository
from src.services.clustering.seed import CentroidSeedService, SeedingResult

router = APIRouter(prefix="/subjects", tags=["cold-start"])


@router.get("/{subject_id}/cold-start/status", response_model=SeedingResult)
async def get_cold_start_status(
    subject_id: uuid.UUID,
    session_count: int = 0,
    syllabus_db: AsyncSession = Depends(get_syllabus_db_session),
) -> SeedingResult:
    service = CentroidSeedService(SyllabusRepository(syllabus_db))
    await service.create_seeds(subject_id)
    return await service.check_seed_status(subject_id, session_count)
