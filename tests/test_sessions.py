"""T07.2 — Session status transitions are constrained to the declared enum."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.models.session import Session, SessionStatus
from src.db.models.subject import Subject
from src.db.models.user import User
from src.db.repositories.exceptions import InvalidStatusTransitionError
from src.db.repositories.session_repo import SessionRepository

pytestmark = pytest.mark.integration


async def _make_subject(db_session: AsyncSession) -> Subject:
    user = User(email=f"{uuid4()}@example.com", hashed_password="hashed")
    db_session.add(user)
    await db_session.flush()
    subject = Subject(user_id=user.id, name=f"Subject-{uuid4()}")
    db_session.add(subject)
    await db_session.flush()
    return subject


class TestSessionStatusConstraint:
    async def test_valid_transition_succeeds(self, db_session: AsyncSession) -> None:
        subject = await _make_subject(db_session)
        repo = SessionRepository(db_session)
        session = await repo.create(subject.id, "content")

        updated = await repo.update_status(session.id, SessionStatus.RECORDING)

        assert updated.status == SessionStatus.RECORDING.value

    async def test_invalid_transition_rejected_by_application_layer(
        self, db_session: AsyncSession
    ) -> None:
        subject = await _make_subject(db_session)
        repo = SessionRepository(db_session)
        session = await repo.create(subject.id, "content")

        with pytest.raises(InvalidStatusTransitionError):
            await repo.update_status(session.id, SessionStatus.COMPLETE)

    async def test_db_check_constraint_is_the_safety_net(self, db_session: AsyncSession) -> None:
        subject = await _make_subject(db_session)
        session = Session(subject_id=subject.id, status="not_a_real_status")
        db_session.add(session)

        with pytest.raises(DBAPIError):
            await db_session.flush()
        await db_session.rollback()

    async def test_session_type_check_constraint(self, db_session: AsyncSession) -> None:
        subject = await _make_subject(db_session)
        with pytest.raises(DBAPIError):
            await db_session.execute(
                text(
                    "INSERT INTO sessions (subject_id, session_type) "
                    "VALUES (:subject_id, 'not_a_real_type')"
                ),
                {"subject_id": subject.id},
            )
            await db_session.flush()
