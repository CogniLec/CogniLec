"""T07.3 — ON DELETE CASCADE from subject removes sessions (and their agent_runs)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.models.agent_run import AgentRun
from src.db.models.session import Session
from src.db.models.subject import Subject
from src.db.models.user import User

pytestmark = pytest.mark.integration


class TestSubjectDeleteCascades:
    async def test_subject_delete_cascades(self, db_session: AsyncSession) -> None:
        user = User(email=f"{uuid4()}@example.com", hashed_password="hashed")
        db_session.add(user)
        await db_session.flush()

        subject = Subject(user_id=user.id, name=f"Subject-{uuid4()}")
        db_session.add(subject)
        await db_session.flush()

        session = Session(subject_id=subject.id)
        db_session.add(session)
        await db_session.flush()

        agent_run = AgentRun(session_id=session.id, agent_id="A1", model="gpt-4o-mini")
        db_session.add(agent_run)
        await db_session.flush()

        await db_session.delete(subject)
        await db_session.flush()

        remaining_sessions = (
            await db_session.execute(select(Session).where(Session.id == session.id))
        ).scalar_one_or_none()
        remaining_runs = (
            await db_session.execute(select(AgentRun).where(AgentRun.id == agent_run.id))
        ).scalar_one_or_none()

        assert remaining_sessions is None
        assert remaining_runs is None
