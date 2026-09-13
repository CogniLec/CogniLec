"""Tests for the S23 session lifecycle state machine (T23.1-T23.5)."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from src.core.state_machine import SessionStateMachine
from src.db.exceptions import InvalidTransitionError
from src.db.models.session import SessionStatus
from src.db.models.subject import Subject
from src.db.models.user import User
from src.db.repositories.session_repo import SessionRepository
from src.workers.retry_queue import RetryQueue
from tests.conftest import DATABASE_URL

pytestmark = pytest.mark.integration

_ALL_STATUSES = list(SessionStatus)
_VALID_PAIRS = {
    (SessionStatus.CREATED, SessionStatus.RECORDING),
    (SessionStatus.RECORDING, SessionStatus.TRANSCRIBED),
    (SessionStatus.TRANSCRIBED, SessionStatus.PROCESSING),
    (SessionStatus.PROCESSING, SessionStatus.COMPLETE),
    (SessionStatus.PROCESSING, SessionStatus.FAILED),
    (SessionStatus.FAILED, SessionStatus.PROCESSING),
    (SessionStatus.FAILED, SessionStatus.TRANSCRIBED),
    (SessionStatus.CREATED, SessionStatus.FAILED),
    (SessionStatus.RECORDING, SessionStatus.FAILED),
}


async def _create_user_and_subject(session: AsyncSession) -> Subject:
    user = User(
        email=f"test-{uuid.uuid4().hex[:8]}@example.com", hashed_password="h", is_active=True
    )
    session.add(user)
    await session.flush()
    subject = Subject(user_id=user.id, name="Test Subject")
    session.add(subject)
    await session.flush()
    return subject


class TestT231TransitionMatrix:
    def test_exhaustive_transition_matrix(self) -> None:
        """T23.1: every (from, to) pair in the full cross product of statuses
        is tested; valid pairs validate True, everything else raises."""
        sm = SessionStateMachine()
        tested_valid = 0
        tested_invalid = 0
        for from_status in _ALL_STATUSES:
            for to_status in _ALL_STATUSES:
                pair = (from_status, to_status)
                if pair in _VALID_PAIRS:
                    assert sm.validate_transition(from_status, to_status) is True
                    tested_valid += 1
                else:
                    with pytest.raises(InvalidTransitionError):
                        sm.validate_transition(from_status, to_status)
                    tested_invalid += 1
        assert tested_valid == len(_VALID_PAIRS) == 9
        assert tested_invalid == len(_ALL_STATUSES) ** 2 - 9


class TestT232FailureMarking:
    async def test_stage_failure_sets_failed_never_complete(self, db_session: AsyncSession) -> None:
        subject = await _create_user_and_subject(db_session)
        repo = SessionRepository(db_session)
        session_obj = await repo.create(subject.id)
        sm = SessionStateMachine()

        await sm.transition(session_obj, SessionStatus.RECORDING, db_session)
        await sm.transition(session_obj, SessionStatus.TRANSCRIBED, db_session)
        await sm.transition(session_obj, SessionStatus.PROCESSING, db_session)

        failed = await sm.transition(
            session_obj,
            SessionStatus.FAILED,
            db_session,
            reason="hallucination_worker raised ValueError",
            stage="hallucination_detection",
        )

        assert failed.status == SessionStatus.FAILED
        assert failed.failure_reason == "hallucination_worker raised ValueError"
        assert failed.failure_stage == "hallucination_detection"
        assert failed.notes_ready is False


class TestT233RetryQueue:
    async def test_failed_session_enqueued_and_dequeued_after_delay(self) -> None:
        queue = RetryQueue()
        queue.RETRY_DELAY_SECONDS = 0  # avoid a real sleep in the test
        session_id = uuid.uuid4()
        try:
            await queue.enqueue(session_id, reason="worker crashed")
            await asyncio.sleep(0.05)
            job = await queue.dequeue()
            assert job is not None
            assert job.session_id == session_id
            assert job.reason == "worker crashed"
        finally:
            await queue.mark_success(session_id)
            await queue.close()


class TestT234RetryFromRetainedTranscript:
    async def test_retry_transitions_from_failed_to_processing_and_increments_count(
        self, db_session: AsyncSession
    ) -> None:
        subject = await _create_user_and_subject(db_session)
        repo = SessionRepository(db_session)
        session_obj = await repo.create(subject.id)
        sm = SessionStateMachine()

        await sm.transition(session_obj, SessionStatus.RECORDING, db_session)
        await sm.transition(session_obj, SessionStatus.TRANSCRIBED, db_session)
        await sm.transition(session_obj, SessionStatus.PROCESSING, db_session)
        await sm.transition(
            session_obj, SessionStatus.FAILED, db_session, reason="boom", stage="worker"
        )
        assert session_obj.retry_count == 0

        retried = await sm.transition(session_obj, SessionStatus.PROCESSING, db_session)

        assert retried.status == SessionStatus.PROCESSING
        assert retried.retry_count == 1
        assert retried.failure_reason is None


class TestT235ConcurrentTransitions:
    async def test_concurrent_transitions_resolve_to_one_consistent_state(self) -> None:
        """T23.5: two concurrent async sessions both attempt CREATED->RECORDING
        via `SELECT ... FOR UPDATE`; both may logically succeed (idempotent
        target state) but the final persisted state is consistent and no
        exception escapes either path."""
        engine = create_async_engine(DATABASE_URL, echo=False)
        async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with async_session() as setup_session:
            user = User(
                email=f"test-{uuid.uuid4().hex[:8]}@example.com",
                hashed_password="h",
                is_active=True,
            )
            setup_session.add(user)
            await setup_session.flush()
            subject = Subject(user_id=user.id, name="Concurrent Subject")
            setup_session.add(subject)
            await setup_session.flush()
            repo = SessionRepository(setup_session)
            session_obj = await repo.create(subject.id)
            session_id = session_obj.id
            await setup_session.commit()

        async def _attempt() -> str:
            async with async_session() as s:
                sm = SessionStateMachine()
                sess = await s.get(type(session_obj), session_id)
                try:
                    updated = await sm.transition(sess, SessionStatus.RECORDING, s)
                except InvalidTransitionError:
                    await s.rollback()
                    return "rejected"
                else:
                    await s.commit()
                    return updated.status

        results = await asyncio.gather(_attempt(), _attempt())
        assert "recording" in results or SessionStatus.RECORDING in results

        async with async_session() as verify_session:
            final = await verify_session.get(type(session_obj), session_id)
            assert final.status == SessionStatus.RECORDING

        await engine.dispose()
