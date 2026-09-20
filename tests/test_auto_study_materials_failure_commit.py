"""Regression test for docs/gaps.md #33g: when `process_session` fails,
the FAILED status/failure_reason it flushes must actually be committed by
`generate_study_materials`, not silently discarded when the caller's
`AsyncSession` context manager closes.

Confirmed live: a real session (`5036ee62-...`) stayed stuck at
`transcribed` forever with `failure_reason` NULL after a genuine pipeline
failure, because `generate_study_materials`'s except block returned 0
without ever calling `db.commit()`.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.models.session import Session, SessionStatus
from src.db.models.user import User
from src.db.partitions.provisioner import PartitionProvisioner
from src.services.orchestration import auto_study_materials

pytestmark = pytest.mark.integration


async def _create_user_subject_session(db: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    user = User(email=f"t-{uuid.uuid4().hex[:8]}@example.com", hashed_password="h", is_active=True)
    db.add(user)
    await db.flush()
    subject = await PartitionProvisioner().provision_subject(db, user.id, name="Subj")
    session_obj = Session(subject_id=subject.id, status=SessionStatus.TRANSCRIBED)
    db.add(session_obj)
    await db.flush()
    await db.commit()
    return subject.id, session_obj.id


async def test_failed_process_session_commits_failure_state(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    subject_id, session_id = await _create_user_subject_session(db_session)

    async def fake_process_session(*, session_id, subject_id, db, **kwargs):
        # Mirror session_pipeline.py's real except block: flush a FAILED
        # transition (not commit) onto `db`, then raise -- exactly what a
        # genuine pipeline failure does today.
        session_obj = await db.get(Session, session_id)
        session_obj.status = SessionStatus.FAILED
        session_obj.failure_reason = "synthetic failure for test"
        session_obj.failure_stage = "T6_synthesize_notes"
        await db.flush()
        raise RuntimeError("synthetic pipeline failure")

    monkeypatch.setattr(auto_study_materials, "process_session", fake_process_session)

    created = await auto_study_materials.generate_study_materials(
        session_id, subject_id, db_session
    )

    assert created == 0

    refreshed = await db_session.get(Session, session_id)
    assert refreshed is not None
    assert refreshed.status == SessionStatus.FAILED
    assert refreshed.failure_reason == "synthetic failure for test"
    assert refreshed.failure_stage == "T6_synthesize_notes"
