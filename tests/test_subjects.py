"""T07.1 – Subject creation and uniqueness constraint tests."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.exceptions import DuplicateKeyError
from src.db.models.user import User
from src.db.repositories.subject_repo import SubjectRepository


async def _create_user(session: AsyncSession, email: str | None = None) -> User:
    """Helper: insert a user row and return it."""
    user = User(
        email=email or f"test-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="hashed",
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


@pytest.mark.integration
class TestSubjectUniquePerUser:
    """T07.1 – Subject creation; duplicate name for same user rejected; same name for different user allowed."""

    async def test_create_subject(self, db_session: AsyncSession) -> None:
        user = await _create_user(db_session)
        repo = SubjectRepository(db_session)

        subject = await repo.create(user.id, "Machine Learning", "CS-229")

        assert subject.id is not None
        assert subject.name == "Machine Learning"
        assert subject.description == "CS-229"
        assert subject.user_id == user.id

    async def test_duplicate_name_same_user_rejected(self, db_session: AsyncSession) -> None:
        user = await _create_user(db_session)
        repo = SubjectRepository(db_session)

        await repo.create(user.id, "Machine Learning", "First")

        with pytest.raises(DuplicateKeyError):
            await repo.create(user.id, "Machine Learning", "Second")

    async def test_same_name_different_users_allowed(self, db_session: AsyncSession) -> None:
        user1 = await _create_user(db_session, "alice@example.com")
        user2 = await _create_user(db_session, "bob@example.com")
        repo = SubjectRepository(db_session)

        s1 = await repo.create(user1.id, "Machine Learning")
        s2 = await repo.create(user2.id, "Machine Learning")

        assert s1.id != s2.id
        assert s1.name == s2.name == "Machine Learning"

    async def test_list_for_user(self, db_session: AsyncSession) -> None:
        user = await _create_user(db_session)
        repo = SubjectRepository(db_session)

        await repo.create(user.id, "Subject A")
        await repo.create(user.id, "Subject B")
        await repo.create(user.id, "Subject C")

        items = await repo.list_for_user(user.id)
        assert len(items) == 3

    async def test_list_by_user_returns_total(self, db_session: AsyncSession) -> None:
        user = await _create_user(db_session)
        repo = SubjectRepository(db_session)

        await repo.create(user.id, "Subject A")
        await repo.create(user.id, "Subject B")

        items, total = await repo.list_by_user(user.id)
        assert len(items) == 2
        assert total == 2

    async def test_get_subject(self, db_session: AsyncSession) -> None:
        user = await _create_user(db_session)
        repo = SubjectRepository(db_session)

        created = await repo.create(user.id, "Machine Learning")
        fetched = await repo.get(created.id)

        assert fetched is not None
        assert fetched.id == created.id

    async def test_get_nonexistent_returns_none(self, db_session: AsyncSession) -> None:
        repo = SubjectRepository(db_session)
        result = await repo.get(uuid.uuid4())
        assert result is None

    async def test_update_subject(self, db_session: AsyncSession) -> None:
        user = await _create_user(db_session)
        repo = SubjectRepository(db_session)

        subject = await repo.create(user.id, "ML", "Old description")
        updated = await repo.update(subject, name="Machine Learning", description="New desc")

        assert updated.name == "Machine Learning"
        assert updated.description == "New desc"

    async def test_delete_subject(self, db_session: AsyncSession) -> None:
        user = await _create_user(db_session)
        repo = SubjectRepository(db_session)

        subject = await repo.create(user.id, "To Delete")
        await repo.delete(subject)

        fetched = await repo.get(subject.id)
        assert fetched is None

    async def test_pagination(self, db_session: AsyncSession) -> None:
        user = await _create_user(db_session)
        repo = SubjectRepository(db_session)

        for i in range(5):
            await repo.create(user.id, f"Subject {i}")

        page1 = await repo.list_for_user(user.id, offset=0, limit=2)
        page2 = await repo.list_for_user(user.id, offset=2, limit=2)
        page3 = await repo.list_for_user(user.id, offset=4, limit=2)

        assert len(page1) == 2
        assert len(page2) == 2
        assert len(page3) == 1
