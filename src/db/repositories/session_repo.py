"""Session repository."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.exceptions import DuplicateKeyError, SessionNotFoundError
from src.db.models.session import Session, SessionStatus


class SessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        subject_id: uuid.UUID,
        session_type: str = "content",
    ) -> Session:
        session_obj = Session(subject_id=subject_id, session_type=session_type)
        self._session.add(session_obj)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise DuplicateKeyError("Failed to create session") from exc
        return session_obj

    async def get(self, session_id: uuid.UUID) -> Session | None:
        return await self._session.get(Session, session_id)

    async def get_or_raise(self, session_id: uuid.UUID) -> Session:
        session_obj = await self.get(session_id)
        if session_obj is None:
            raise SessionNotFoundError(f"Session {session_id} not found")
        return session_obj

    async def list_for_subject(
        self, subject_id: uuid.UUID, *, offset: int = 0, limit: int = 50
    ) -> list[Session]:
        stmt = (
            select(Session)
            .where(Session.subject_id == subject_id)
            .order_by(Session.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_subject(
        self, subject_id: uuid.UUID, offset: int = 0, limit: int = 50
    ) -> tuple[list[Session], int]:
        items = await self.list_for_subject(subject_id, offset=offset, limit=limit)
        count_stmt = (
            select(func.count()).select_from(Session).where(Session.subject_id == subject_id)
        )
        count_result = await self._session.execute(count_stmt)
        total = count_result.scalar_one()
        return items, total

    async def update_status(self, session_obj: Session, status: SessionStatus) -> Session:
        session_obj.status = status
        await self._session.flush()
        return session_obj

    async def update_audio_quality(self, session_obj: Session, score: float | None) -> Session:
        """Persist the aggregated session audio-quality score (S18)."""
        session_obj.audio_quality = score
        await self._session.flush()
        return session_obj
