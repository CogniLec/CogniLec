"""Session repository."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.models.session import Session, SessionStatus
from src.db.repositories.exceptions import (
    InvalidStatusTransitionError,
    SessionNotFoundError,
)

# Allowed status transitions (S07 state machine; S23 formalizes further).
_VALID_TRANSITIONS: dict[SessionStatus, set[SessionStatus]] = {
    SessionStatus.CREATED: {SessionStatus.RECORDING, SessionStatus.FAILED},
    SessionStatus.RECORDING: {SessionStatus.TRANSCRIBED, SessionStatus.FAILED},
    SessionStatus.TRANSCRIBED: {SessionStatus.PROCESSING, SessionStatus.FAILED},
    SessionStatus.PROCESSING: {SessionStatus.COMPLETE, SessionStatus.FAILED},
    SessionStatus.COMPLETE: set(),
    SessionStatus.FAILED: set(),
}


class SessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, subject_id: UUID, session_type: str) -> Session:
        record = Session(subject_id=subject_id, session_type=session_type)
        self._session.add(record)
        await self._session.flush()
        return record

    async def get_by_id(self, session_id: UUID) -> Session | None:
        return await self._session.get(Session, session_id)

    async def update_status(self, session_id: UUID, new_status: SessionStatus) -> Session:
        record = await self.get_by_id(session_id)
        if record is None:
            raise SessionNotFoundError(session_id)

        current_status = SessionStatus(record.status)
        if new_status not in _VALID_TRANSITIONS[current_status]:
            raise InvalidStatusTransitionError(current_status.value, new_status.value)

        record.status = new_status.value
        await self._session.flush()
        return record

    async def list_by_subject(
        self, subject_id: UUID, offset: int, limit: int
    ) -> tuple[list[Session], int]:
        items_stmt = (
            select(Session)
            .where(Session.subject_id == subject_id)
            .order_by(Session.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        count_stmt = (
            select(func.count()).select_from(Session).where(Session.subject_id == subject_id)
        )

        items = (await self._session.execute(items_stmt)).scalars().all()
        total = (await self._session.execute(count_stmt)).scalar_one()
        return list(items), total
