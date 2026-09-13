"""Subject repository."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.exceptions import DuplicateKeyError, SubjectNotFoundError
from src.db.models.subject import Subject


class SubjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self, user_id: uuid.UUID, name: str, description: str | None = None
    ) -> Subject:
        subject = Subject(user_id=user_id, name=name, description=description)
        self._session.add(subject)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise DuplicateKeyError(f"Subject '{name}' already exists for this user") from exc
        return subject

    async def get(self, subject_id: uuid.UUID) -> Subject | None:
        return await self._session.get(Subject, subject_id)

    async def get_or_raise(self, subject_id: uuid.UUID) -> Subject:
        subject = await self.get(subject_id)
        if subject is None:
            raise SubjectNotFoundError(f"Subject {subject_id} not found")
        return subject

    async def list_for_user(
        self, user_id: uuid.UUID, *, offset: int = 0, limit: int = 50
    ) -> list[Subject]:
        stmt = (
            select(Subject)
            .where(Subject.user_id == user_id)
            .order_by(Subject.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_user(
        self, user_id: uuid.UUID, offset: int = 0, limit: int = 50
    ) -> tuple[list[Subject], int]:
        items = await self.list_for_user(user_id, offset=offset, limit=limit)
        total = await self.count_for_user(user_id)
        return items, total

    async def count_for_user(self, user_id: uuid.UUID) -> int:
        stmt = select(func.count()).select_from(Subject).where(Subject.user_id == user_id)
        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def update(
        self, subject: Subject, *, name: str | None = None, description: str | None = None
    ) -> Subject:
        if name is not None:
            subject.name = name
        if description is not None:
            subject.description = description
        await self._session.flush()
        return subject

    async def delete(self, subject: Subject) -> None:
        await self._session.delete(subject)
        await self._session.flush()
