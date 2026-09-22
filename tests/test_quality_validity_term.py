"""Regression test for the quality-loop `validity` term (docs/audit/
self-improving-loop.md): a flashcard's answer must be judged against the
note-sections/utterances it was actually generated from, resolved via
`Flashcard.source_result_ids`.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.models.flashcard import Flashcard
from src.db.models.note_section import NoteSection
from src.db.models.user import User
from src.db.partitions.provisioner import PartitionProvisioner
from src.services.quality.scorer import _validity_term
from src.services.study.fsrs_scheduler import new_card_fields

pytestmark = pytest.mark.integration


class FakeJudge:
    """Returns True only when the card's front text appears in the source."""

    def supported(self, claim: str, source: str) -> bool | None:
        front = claim.split("\n", 1)[0]
        return front in source


async def _subject(db: AsyncSession) -> uuid.UUID:
    user = User(email=f"t-{uuid.uuid4().hex[:8]}@example.com", hashed_password="h", is_active=True)
    db.add(user)
    await db.flush()
    subject = await PartitionProvisioner().provision_subject(db, user.id, name="Subj")
    await db.commit()
    return subject.id


async def test_validity_term_uses_cards_own_source_not_whole_subject(
    db_session: AsyncSession,
) -> None:
    subject_id = await _subject(db_session)

    supported_section = NoteSection(
        subject_id=subject_id,
        heading="Real",
        body_md="Photosynthesis converts light to chemical energy.",
        depth=0,
        ordinal=0,
    )
    unrelated_section = NoteSection(
        subject_id=subject_id,
        heading="Unrelated",
        body_md="Mitochondria is the powerhouse of the cell.",
        depth=0,
        ordinal=1,
    )
    db_session.add_all([supported_section, unrelated_section])
    await db_session.flush()

    good_card = Flashcard(
        subject_id=subject_id,
        topic_label="Photosynthesis",
        front="Photosynthesis converts light to chemical energy.",
        back="A",
        source_result_ids=[str(supported_section.id)],
        **new_card_fields(),
    )
    bad_card = Flashcard(
        subject_id=subject_id,
        topic_label="Photosynthesis",
        front="Photosynthesis converts light to chemical energy.",
        back="A",
        # Wrong source on purpose: this card's own citation doesn't
        # contain its claim, even though some OTHER note in the subject
        # does -- validity must fail it rather than pass on the subject's
        # whole note pool.
        source_result_ids=[str(unrelated_section.id)],
        **new_card_fields(),
    )
    db_session.add_all([good_card, bad_card])
    await db_session.flush()

    card_rows = [
        (good_card.front, good_card.back, good_card.source_result_ids),
        (bad_card.front, bad_card.back, bad_card.source_result_ids),
    ]
    result = await _validity_term(db_session, subject_id, card_rows, FakeJudge())
    assert result == 0.5


async def test_validity_term_none_when_no_source_ids_resolve(db_session: AsyncSession) -> None:
    subject_id = await _subject(db_session)
    card_rows = [("Q", "A", [str(uuid.uuid4())])]
    result = await _validity_term(db_session, subject_id, card_rows, FakeJudge())
    assert result is None
