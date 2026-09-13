"""S52 — subject dashboard: declared vs covered vs outstanding syllabus items."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies.database import get_db_session, get_syllabus_db_session
from src.db.repositories.coverage_repo import CoverageRepository
from src.db.repositories.session_repo import SessionRepository
from src.db.repositories.subject_repo import SubjectRepository
from src.db.repositories.topic_repo import TopicRepository
from src.services.coverage.coverage_service import CoverageService
from src.services.coverage.models import SyllabusCoverageSummary

router = APIRouter(prefix="/subjects", tags=["dashboard"])


class SessionSummary(BaseModel):
    session_id: uuid.UUID
    status: str


class SubjectDashboard(BaseModel):
    subject_id: uuid.UUID
    subject_title: str
    total_sessions: int
    total_topics: int
    coverage: SyllabusCoverageSummary
    recent_sessions: list[SessionSummary]


@router.get("/{subject_id}/dashboard", response_model=SubjectDashboard)
async def get_dashboard(
    subject_id: uuid.UUID,
    syllabus_db: AsyncSession = Depends(get_syllabus_db_session),
    main_db: AsyncSession = Depends(get_db_session),
) -> SubjectDashboard:
    subject_repo = SubjectRepository(main_db)
    session_repo = SessionRepository(main_db)
    topic_repo = TopicRepository(main_db)
    coverage_service = CoverageService(CoverageRepository(syllabus_db, main_db))

    subject = await subject_repo.get_or_raise(subject_id)
    sessions = await session_repo.list_for_subject(subject_id)
    topics = await topic_repo.list_for_subject(subject_id)
    coverage = await coverage_service.get_summary(subject_id)

    return SubjectDashboard(
        subject_id=subject_id,
        subject_title=subject.name,
        total_sessions=len(sessions),
        total_topics=len(topics),
        coverage=coverage,
        recent_sessions=[
            SessionSummary(session_id=s.id, status=s.status) for s in sessions[-5:]
        ],
    )
