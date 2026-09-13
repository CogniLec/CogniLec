"""Integration tests for S45 - note persistence & idempotency (T45.1-T45.5)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.models.session import SessionStatus
from src.db.models.subject import Subject
from src.db.models.user import User
from src.db.partitions.provisioner import PartitionProvisioner
from src.db.repositories.session_repo import SessionRepository
from src.db.repositories.utterance_repo import UtteranceRepository
from src.services.synthesis.note_persistence import (
    NoteWriteRejectedError,
    mark_notes_ready,
    persist_note_sections,
)
from src.services.synthesis.note_synthesis import NoteSectionOutput

pytestmark = pytest.mark.integration


async def _setup(db_session: AsyncSession) -> tuple[Subject, uuid.UUID, str]:
    user = User(email=f"t-{uuid.uuid4().hex[:8]}@example.com", hashed_password="h", is_active=True)
    db_session.add(user)
    await db_session.flush()
    subject = await PartitionProvisioner().provision_subject(db_session, user.id, name="Subj")

    session_repo = SessionRepository(db_session)
    session_obj = await session_repo.create(subject.id)

    utterance_repo = UtteranceRepository(db_session)
    await utterance_repo.bulk_insert(
        subject.id,
        [
            {
                "session_id": session_obj.id,
                "seq": 0,
                "start_ms": 0,
                "end_ms": 100,
                "text": "hello",
                "asr_confidence": 0.9,
                "words": [],
                "speaker_tag": "SPK_A",
                "embed_model_ver": "v1",
            }
        ],
    )
    utterances = await utterance_repo.get_by_session(subject.id, session_obj.id)
    return subject, session_obj.id, str(utterances[0].id)


@pytest.mark.asyncio
async def test_t45_2_rejects_write_with_no_db1_record(db_session: AsyncSession) -> None:
    subject, session_id, _ = await _setup(db_session)
    sections = [
        NoteSectionOutput(
            heading="Bad", body_md="x", depth=0, ordinal=0, source_utt_ids=[str(uuid.uuid4())]
        )
    ]
    with pytest.raises(NoteWriteRejectedError):
        await persist_note_sections(db_session, subject.id, session_id, None, sections)


@pytest.mark.asyncio
async def test_t45_1_rerunning_flow_does_not_duplicate_sections(db_session: AsyncSession) -> None:
    subject, session_id, utt_id = await _setup(db_session)
    sections = [
        NoteSectionOutput(heading="H1", body_md="v1", depth=0, ordinal=0, source_utt_ids=[utt_id])
    ]

    await persist_note_sections(db_session, subject.id, session_id, None, sections)
    updated = [
        NoteSectionOutput(heading="H1", body_md="v2", depth=0, ordinal=0, source_utt_ids=[utt_id])
    ]
    await persist_note_sections(db_session, subject.id, session_id, None, updated)

    result = await db_session.execute(
        text("SELECT body_md FROM note_sections WHERE subject_id = :s AND session_id = :sess"),
        {"s": subject.id, "sess": session_id},
    )
    rows = result.fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "v2"


@pytest.mark.asyncio
async def test_t45_3_section_embeddings_present_and_queryable(db_session: AsyncSession) -> None:
    subject, session_id, utt_id = await _setup(db_session)
    sections = [
        NoteSectionOutput(heading="H1", body_md="v1", depth=0, ordinal=0, source_utt_ids=[utt_id])
    ]
    await persist_note_sections(
        db_session,
        subject.id,
        session_id,
        None,
        sections,
        embeddings_by_ordinal={0: [0.1] * 1024},
    )
    result = await db_session.execute(
        text(
            "SELECT embedding IS NOT NULL FROM note_sections WHERE subject_id = :s AND session_id = :sess"
        ),
        {"s": subject.id, "sess": session_id},
    )
    assert result.fetchone()[0] is True


@pytest.mark.asyncio
async def test_t45_4_partial_failure_writes_nothing(db_session: AsyncSession) -> None:
    subject, session_id, utt_id = await _setup(db_session)
    sections = [
        NoteSectionOutput(
            heading="Good", body_md="ok", depth=0, ordinal=0, source_utt_ids=[utt_id]
        ),
        NoteSectionOutput(
            heading="Bad", body_md="bad", depth=0, ordinal=1, source_utt_ids=[str(uuid.uuid4())]
        ),
    ]
    with pytest.raises(NoteWriteRejectedError):
        await persist_note_sections(db_session, subject.id, session_id, None, sections)

    result = await db_session.execute(
        text("SELECT count(*) FROM note_sections WHERE subject_id = :s AND session_id = :sess"),
        {"s": subject.id, "sess": session_id},
    )
    assert result.fetchone()[0] == 0


@pytest.mark.asyncio
async def test_t45_5_notes_ready_set_only_after_successful_persist(
    db_session: AsyncSession,
) -> None:
    subject, session_id, utt_id = await _setup(db_session)
    session_repo = SessionRepository(db_session)
    session_obj = await session_repo.get_or_raise(session_id)
    assert session_obj.notes_ready is False

    sections = [
        NoteSectionOutput(heading="H1", body_md="v1", depth=0, ordinal=0, source_utt_ids=[utt_id])
    ]
    await persist_note_sections(db_session, subject.id, session_id, None, sections)
    await mark_notes_ready(db_session, session_obj)

    assert session_obj.notes_ready is True
    assert session_obj.status == SessionStatus.COMPLETE
