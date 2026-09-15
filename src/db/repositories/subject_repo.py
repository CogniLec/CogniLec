"""Subject repository."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from src.api.schemas.subject import SubjectCreate, SubjectUpdate
from src.db.models.subject import Subject
from src.db.repositories.exceptions import DuplicateKeyError


class SubjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, user_id: UUID, data: SubjectCreate) -> Subject:
        subject = Subject(user_id=user_id, name=data.name, description=data.description)
        self._session.add(subject)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            await self._session.rollback()
            raise DuplicateKeyError(data.name) from exc
        return subject

    async def get_by_id(self, subject_id: UUID) -> Subject | None:
        return await self._session.get(Subject, subject_id)

    async def list_by_user(
        self, user_id: UUID, offset: int, limit: int
    ) -> tuple[list[Subject], int]:
        items_stmt = (
            select(Subject)
            .where(Subject.user_id == user_id)
            .order_by(Subject.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        count_stmt = select(func.count()).select_from(Subject).where(Subject.user_id == user_id)

        items = (await self._session.execute(items_stmt)).scalars().all()
        total = (await self._session.execute(count_stmt)).scalar_one()
        return list(items), total

    async def update(self, subject_id: UUID, data: SubjectUpdate) -> Subject | None:
        subject = await self.get_by_id(subject_id)
        if subject is None:
            return None

        updates = data.model_dump(exclude_unset=True)
        for field, value in updates.items():
            setattr(subject, field, value)

        try:
            await self._session.flush()
        except IntegrityError as exc:
            await self._session.rollback()
            raise DuplicateKeyError(subject.name) from exc
        return subject

    async def delete(self, subject_id: UUID) -> bool:
        subject = await self.get_by_id(subject_id)
        if subject is None:
            return False
        await self._session.delete(subject)
        await self._session.flush()
        return True
