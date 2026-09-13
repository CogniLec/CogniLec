"""T07.2 – Session status constraint tests."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.models.session import SessionStatus
from src.db.models.subject import Subject
from src.db.models.user import User
from src.db.repositories.session_repo import SessionRepository


async def _create_user_and_subject(session: AsyncSession) -> Subject:
    """Helper: create a user and subject, return the subject."""
    user = User(
        email=f"test-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="hashed",
        is_active=True,
    )
    session.add(user)
    await session.flush()

    subject = Subject(user_id=user.id, name="Test Subject")
    session.add(subject)
    await session.flush()
    return subject


@pytest.mark.integration
class TestSessionStatusConstraint:
    """T07.2 – Session status transitions constrained to declared enum."""

    async def test_create_session_default_status(self, db_session: AsyncSession) -> None:
        subject = await _create_user_and_subject(db_session)
        repo = SessionRepository(db_session)

        session_obj = await repo.create(subject.id, "content")

        assert session_obj.status == SessionStatus.CREATED
        assert session_obj.session_type == "content"
        assert session_obj.notes_ready is False

    async def test_update_status_to_recording(self, db_session: AsyncSession) -> None:
        subject = await _create_user_and_subject(db_session)
        repo = SessionRepository(db_session)

        session_obj = await repo.create(subject.id)
        updated = await repo.update_status(session_obj, SessionStatus.RECORDING)

        assert updated.status == SessionStatus.RECORDING

    async def test_update_status_to_transcribed(self, db_session: AsyncSession) -> None:
        subject = await _create_user_and_subject(db_session)
        repo = SessionRepository(db_session)

        session_obj = await repo.create(subject.id)
        await repo.update_status(session_obj, SessionStatus.RECORDING)
        updated = await repo.update_status(session_obj, SessionStatus.TRANSCRIBED)

        assert updated.status == SessionStatus.TRANSCRIBED

    async def test_update_status_to_complete(self, db_session: AsyncSession) -> None:
        subject = await _create_user_and_subject(db_session)
        repo = SessionRepository(db_session)

        session_obj = await repo.create(subject.id)
        await repo.update_status(session_obj, SessionStatus.RECORDING)
        await repo.update_status(session_obj, SessionStatus.TRANSCRIBED)
        await repo.update_status(session_obj, SessionStatus.PROCESSING)
        updated = await repo.update_status(session_obj, SessionStatus.COMPLETE)

        assert updated.status == SessionStatus.COMPLETE

    async def test_update_status_to_failed(self, db_session: AsyncSession) -> None:
        subject = await _create_user_and_subject(db_session)
        repo = SessionRepository(db_session)

        session_obj = await repo.create(subject.id)
        await repo.update_status(session_obj, SessionStatus.RECORDING)
        updated = await repo.update_status(session_obj, SessionStatus.FAILED)

        assert updated.status == SessionStatus.FAILED

    async def test_invalid_status_rejected_by_db(self, db_session: AsyncSession) -> None:
        subject = await _create_user_and_subject(db_session)

        # Directly insert with invalid status to test DB check constraint
        with pytest.raises(IntegrityError):
            await db_session.execute(
                text(
                    "INSERT INTO sessions (subject_id, session_type, status, notes_ready) "
                    "VALUES (:sid, 'content', 'invalid_status', false)"
                ),
                {"sid": subject.id},
            )
            await db_session.flush()

    async def test_list_for_subject(self, db_session: AsyncSession) -> None:
        subject = await _create_user_and_subject(db_session)
        repo = SessionRepository(db_session)

        await repo.create(subject.id, "content")
        await repo.create(subject.id, "syllabus")

        sessions = await repo.list_for_subject(subject.id)
        assert len(sessions) == 2

    async def test_get_session(self, db_session: AsyncSession) -> None:
        subject = await _create_user_and_subject(db_session)
        repo = SessionRepository(db_session)

        created = await repo.create(subject.id)
        fetched = await repo.get(created.id)

        assert fetched is not None
        assert fetched.id == created.id

    async def test_get_nonexistent_returns_none(self, db_session: AsyncSession) -> None:
        repo = SessionRepository(db_session)
        result = await repo.get(uuid.uuid4())
        assert result is None
