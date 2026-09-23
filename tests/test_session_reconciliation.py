"""Tests for session_reconciliation.py: recovering `recording` sessions
that were never finalized (docs/gaps.md-style regression -- a real
441-utterance session sat at `recording` for over a day with no way to
recover except manual DB surgery).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.models.session import SessionStatus
from src.db.models.user import User
from src.db.models.utterance import Utterance
from src.db.partitions.provisioner import PartitionProvisioner
from src.db.repositories.session_repo import SessionRepository
from src.services.orchestration.session_reconciliation import (
    reconcile_stale_recording_sessions,
    reconcile_stale_transcribed_sessions,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def _subject_and_recording_session(
    db: AsyncSession, *, created_at: datetime
) -> tuple[uuid.UUID, uuid.UUID]:
    user = User(email=f"t-{uuid.uuid4().hex[:8]}@example.com", hashed_password="h", is_active=True)
    db.add(user)
    await db.flush()
    subject = await PartitionProvisioner().provision_subject(db, user.id, name="Subj")
    repo = SessionRepository(db)
    session_obj = await repo.create(subject.id, "content")
    session_obj.created_at = created_at
    session_obj.status = SessionStatus.RECORDING
    await db.flush()
    await db.commit()
    return subject.id, session_obj.id


async def test_recent_recording_session_is_left_alone(db_session: AsyncSession) -> None:
    _subject_id, session_id = await _subject_and_recording_session(
        db_session, created_at=datetime.now(UTC)
    )
    result = await reconcile_stale_recording_sessions(db_session, idle_after=timedelta(minutes=15))
    assert result.finalized_session_ids == []
    assert result.failed_session_ids == []

    session_obj = await SessionRepository(db_session).get_or_raise(session_id)
    assert session_obj.status == SessionStatus.RECORDING


async def test_stale_session_with_utterances_is_finalized_not_failed(
    db_session: AsyncSession,
) -> None:
    old = datetime.now(UTC) - timedelta(hours=25)
    subject_id, session_id = await _subject_and_recording_session(db_session, created_at=old)
    db_session.add(
        Utterance(
            subject_id=subject_id,
            session_id=session_id,
            seq=0,
            start_ms=0,
            end_ms=1000,
            text="real transcribed content",
            embed_model_ver="v1",
            created_at=old + timedelta(minutes=1),
        )
    )
    await db_session.commit()

    result = await reconcile_stale_recording_sessions(db_session, idle_after=timedelta(minutes=15))
    assert result.finalized_session_ids == [(session_id, subject_id)]
    assert result.failed_session_ids == []

    session_obj = await SessionRepository(db_session).get_or_raise(session_id)
    assert session_obj.status == SessionStatus.TRANSCRIBED


async def test_stale_session_with_no_utterances_is_marked_failed(db_session: AsyncSession) -> None:
    old = datetime.now(UTC) - timedelta(hours=25)
    _subject_id, session_id = await _subject_and_recording_session(db_session, created_at=old)

    result = await reconcile_stale_recording_sessions(db_session, idle_after=timedelta(minutes=15))
    assert result.finalized_session_ids == []
    assert result.failed_session_ids == [session_id]

    session_obj = await SessionRepository(db_session).get_or_raise(session_id)
    assert session_obj.status == SessionStatus.FAILED
    assert session_obj.failure_reason is not None
    assert session_obj.failure_stage == "recording"


async def test_stale_transcribed_session_is_retried_and_bookkept(db_session: AsyncSession) -> None:
    old = datetime.now(UTC) - timedelta(hours=1)
    subject_id, session_id = await _subject_and_recording_session(db_session, created_at=old)
    session_obj = await SessionRepository(db_session).get_or_raise(session_id)
    session_obj.status = SessionStatus.TRANSCRIBED
    session_obj.notes_ready = False
    await db_session.commit()

    to_retry = await reconcile_stale_transcribed_sessions(
        db_session, idle_after=timedelta(minutes=45)
    )
    assert to_retry == [(session_id, subject_id)]

    db_session.expire_all()
    refreshed = await SessionRepository(db_session).get_or_raise(session_id)
    assert refreshed.retry_count == 1
    assert refreshed.last_retry_at is not None


async def test_recently_transcribed_session_is_not_retried_yet(db_session: AsyncSession) -> None:
    _subject_id, session_id = await _subject_and_recording_session(
        db_session, created_at=datetime.now(UTC)
    )
    session_obj = await SessionRepository(db_session).get_or_raise(session_id)
    session_obj.status = SessionStatus.TRANSCRIBED
    session_obj.notes_ready = False
    await db_session.commit()

    to_retry = await reconcile_stale_transcribed_sessions(
        db_session, idle_after=timedelta(minutes=45)
    )
    assert to_retry == []


async def test_transcribed_retry_count_caps_out(db_session: AsyncSession) -> None:
    old = datetime.now(UTC) - timedelta(hours=1)
    _subject_id, session_id = await _subject_and_recording_session(db_session, created_at=old)
    session_obj = await SessionRepository(db_session).get_or_raise(session_id)
    session_obj.status = SessionStatus.TRANSCRIBED
    session_obj.notes_ready = False
    session_obj.retry_count = 3
    await db_session.commit()

    to_retry = await reconcile_stale_transcribed_sessions(
        db_session, idle_after=timedelta(minutes=45), max_retries=3
    )
    assert to_retry == []


async def test_ready_transcribed_session_is_never_retried(db_session: AsyncSession) -> None:
    old = datetime.now(UTC) - timedelta(hours=1)
    _subject_id, session_id = await _subject_and_recording_session(db_session, created_at=old)
    session_obj = await SessionRepository(db_session).get_or_raise(session_id)
    session_obj.status = SessionStatus.TRANSCRIBED
    session_obj.notes_ready = True
    await db_session.commit()

    to_retry = await reconcile_stale_transcribed_sessions(
        db_session, idle_after=timedelta(minutes=45)
    )
    assert to_retry == []


async def test_activity_measured_from_last_utterance_not_session_creation(
    db_session: AsyncSession,
) -> None:
    """A session created long ago but with a recent utterance (still
    actively recording a long lecture) must not be swept -- only genuinely
    idle sessions should be touched."""
    old_created = datetime.now(UTC) - timedelta(hours=2)
    subject_id, session_id = await _subject_and_recording_session(
        db_session, created_at=old_created
    )
    db_session.add(
        Utterance(
            subject_id=subject_id,
            session_id=session_id,
            seq=0,
            start_ms=0,
            end_ms=1000,
            text="still going",
            embed_model_ver="v1",
            created_at=datetime.now(UTC) - timedelta(minutes=1),
        )
    )
    await db_session.commit()

    result = await reconcile_stale_recording_sessions(db_session, idle_after=timedelta(minutes=15))
    assert result.finalized_session_ids == []
    assert result.failed_session_ids == []
