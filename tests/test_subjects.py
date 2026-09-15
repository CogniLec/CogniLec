"""T07.1 — Subject creation and per-user uniqueness."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from src.api.schemas.subject import SubjectCreate
from src.db.models.user import User
from src.db.repositories.exceptions import DuplicateKeyError
from src.db.repositories.subject_repo import SubjectRepository

pytestmark = pytest.mark.integration


async def _make_user(db_session: AsyncSession, email: str) -> User:
    user = User(email=email, hashed_password="hashed")
    db_session.add(user)
    await db_session.flush()
    return user


class TestSubjectUniquePerUser:
    async def test_subject_unique_per_user(self, db_session: AsyncSession) -> None:
        user = await _make_user(db_session, f"{uuid4()}@example.com")
        repo = SubjectRepository(db_session)

        await repo.create(user.id, SubjectCreate(name="Machine Learning"))

        with pytest.raises(DuplicateKeyError):
            await repo.create(user.id, SubjectCreate(name="Machine Learning"))

    async def test_same_name_different_user_allowed(self, db_session: AsyncSession) -> None:
        user_a = await _make_user(db_session, f"{uuid4()}@example.com")
        user_b = await _make_user(db_session, f"{uuid4()}@example.com")
        repo = SubjectRepository(db_session)

        subject_a = await repo.create(user_a.id, SubjectCreate(name="Machine Learning"))
        subject_b = await repo.create(user_b.id, SubjectCreate(name="Machine Learning"))

        assert subject_a.id != subject_b.id
        assert subject_a.name == subject_b.name == "Machine Learning"


class TestSubjectListing:
    async def test_list_by_user(self, db_session: AsyncSession) -> None:
        user = await _make_user(db_session, f"{uuid4()}@example.com")
        repo = SubjectRepository(db_session)
        await repo.create(user.id, SubjectCreate(name="Math"))
        await repo.create(user.id, SubjectCreate(name="Physics"))

        items, total = await repo.list_by_user(user.id, offset=0, limit=50)

        assert total == 2
        assert {item.name for item in items} == {"Math", "Physics"}
