"""T07.3 - ON DELETE CASCADE tests."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.models.agent_run import AgentRun
from src.db.models.session import Session
from src.db.models.subject import Subject
from src.db.models.user import User
from src.db.repositories.session_repo import SessionRepository


async def _create_full_cascade(session: AsyncSession) -> tuple[User, Subject, Session, AgentRun]:
    """Helper: create user → subject → session → agent_run, return all."""
    user = User(
        email=f"cascade-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="hashed",
        is_active=True,
    )
    session.add(user)
    await session.flush()

    subject = Subject(user_id=user.id, name="Cascade Test")
    session.add(subject)
    await session.flush()

    session_obj = Session(subject_id=subject.id, session_type="content")
    session.add(session_obj)
    await session.flush()

    agent_run = AgentRun(
        session_id=session_obj.id,
        agent_id="A1",
        model="test-model",
        outcome="pending",
    )
    session.add(agent_run)
    await session.flush()

    return user, subject, session_obj, agent_run


async def _exists(session: AsyncSession, model: type, id_: uuid.UUID) -> bool:
    """Check row existence via a fresh SELECT, bypassing the ORM identity map.

    `session.get()` returns a stale identity-mapped instance for rows that
    were removed by a database-level ON DELETE CASCADE (rather than through
    the ORM), since the ORM never learns those rows were removed. A direct
    SELECT always reflects real database state.
    """
    result = await session.execute(select(model.id).where(model.id == id_))
    return result.scalar_one_or_none() is not None


@pytest.mark.integration
class TestSubjectDeleteCascades:
    """T07.3 - ON DELETE CASCADE from subject removes sessions."""

    async def test_delete_subject_removes_sessions(self, db_session: AsyncSession) -> None:
        _user, subject, session_obj, agent_run = await _create_full_cascade(db_session)

        # Delete the subject
        await db_session.delete(subject)
        await db_session.flush()

        # Verify session is gone
        assert not await _exists(db_session, Session, session_obj.id)

        # Verify agent_run is gone (cascade through session)
        assert not await _exists(db_session, AgentRun, agent_run.id)

    async def test_delete_user_removes_subjects(self, db_session: AsyncSession) -> None:
        user, subject, session_obj, agent_run = await _create_full_cascade(db_session)

        # Delete the user
        await db_session.delete(user)
        await db_session.flush()

        # Verify everything is gone
        assert not await _exists(db_session, Subject, subject.id)
        assert not await _exists(db_session, Session, session_obj.id)
        assert not await _exists(db_session, AgentRun, agent_run.id)

    async def test_delete_session_removes_agent_runs(self, db_session: AsyncSession) -> None:
        _user, subject, session_obj, agent_run = await _create_full_cascade(db_session)

        # Delete the session
        await db_session.delete(session_obj)
        await db_session.flush()

        # Verify agent_run is gone
        assert not await _exists(db_session, AgentRun, agent_run.id)

        # Verify subject still exists
        assert await _exists(db_session, Subject, subject.id)

    async def test_multiple_sessions_cascade(self, db_session: AsyncSession) -> None:
        _user, subject, _, _ = await _create_full_cascade(db_session)
        repo = SessionRepository(db_session)

        # Create additional sessions
        s1 = await repo.create(subject.id, "content")
        s2 = await repo.create(subject.id, "syllabus")

        # Add agent runs to each
        for sess in [s1, s2]:
            ar = AgentRun(session_id=sess.id, agent_id="A1", model="m", outcome="pending")
            db_session.add(ar)
        await db_session.flush()

        # Delete subject
        await db_session.delete(subject)
        await db_session.flush()

        # All sessions and agent runs should be gone
        assert not await _exists(db_session, Session, s1.id)
        assert not await _exists(db_session, Session, s2.id)
