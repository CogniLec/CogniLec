"""Regression test: flashcard generation must not silently produce 0 cards
for a subject that has real persisted notes but zero Topic rows.

Confirmed live (docs/audit/self-improving-loop.md-adjacent finding): A2
(note synthesis) was redesigned to work from the full session transcript
and no longer depends on clustering (T3/T4) succeeding, so a session can
get real, persisted note sections even when HDBSCAN finds zero stable
clusters. `generate_flashcards_for_subject` was never updated to match --
it only ever looped over Topic rows, so a subject whose first session hit
this (a real ~20-minute lecture: 46 relevant utterances, 9 persisted note
sections, 0 Topic rows) got a 409 "no persisted notes/topics yet" despite
having real notes.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.models.note_section import NoteSection
from src.db.models.user import User
from src.db.partitions.provisioner import PartitionProvisioner
from src.services.orchestration.auto_study_materials import generate_flashcards_for_subject
from src.services.study import flashcards as flashcards_module

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def _subject_with_notes_but_no_topics(db: AsyncSession) -> uuid.UUID:
    user = User(email=f"t-{uuid.uuid4().hex[:8]}@example.com", hashed_password="h", is_active=True)
    db.add(user)
    await db.flush()
    subject = await PartitionProvisioner().provision_subject(db, user.id, name="Subj")
    db.add(
        NoteSection(
            subject_id=subject.id,
            heading="Advertising and Persuasion",
            body_md="Real synthesized content.",
            depth=0,
            ordinal=0,
            topic_id=None,
        )
    )
    await db.commit()
    return subject.id


async def test_generates_flashcards_from_note_headings_when_no_topics_exist(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    subject_id = await _subject_with_notes_but_no_topics(db_session)

    async def fake_generate_for_topic(self, db, subject_id, topic_label, count):
        assert topic_label == "Advertising and Persuasion"
        card = flashcards_module.GeneratedFlashcard(front="Q", back="A")
        return [card], ["src-1"]

    monkeypatch.setattr(
        flashcards_module.FlashcardGenerator, "generate_for_topic", fake_generate_for_topic
    )

    created = await generate_flashcards_for_subject(db_session, subject_id, router=object())
    assert created == 1


async def test_no_flashcards_and_no_crash_when_neither_topics_nor_notes_exist(
    db_session: AsyncSession,
) -> None:
    user = User(email=f"t-{uuid.uuid4().hex[:8]}@example.com", hashed_password="h", is_active=True)
    db_session.add(user)
    await db_session.flush()
    subject = await PartitionProvisioner().provision_subject(db_session, user.id, name="Subj")
    await db_session.commit()

    created = await generate_flashcards_for_subject(db_session, subject.id, router=object())
    assert created == 0
