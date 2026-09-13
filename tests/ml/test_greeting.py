"""S33 — greeting keyword detector tests (T33.1, T33.2)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.models.session import Session
from src.db.models.user import User
from src.db.models.utterance import Utterance
from src.db.partitions.provisioner import PartitionProvisioner
from src.ml.greeting import detect_greetings


@dataclass
class FakeUtterance:
    id: uuid.UUID
    seq: int
    text: str
    start_ms: int
    end_ms: int


@pytest.mark.unit
class TestT331GreetingPhrasingsAndLanguages:
    def test_detects_greetings_across_phrasings(self) -> None:
        session_id = uuid.uuid4()
        utterances = [
            FakeUtterance(uuid.uuid4(), 0, "Good morning everyone", 0, 1000),
            FakeUtterance(uuid.uuid4(), 1, "Welcome to today's lecture", 1000, 2000),
            FakeUtterance(uuid.uuid4(), 2, "Let's talk about matrices", 2000, 3000),
        ]

        result = detect_greetings(session_id, utterances)

        assert result.has_greeting is True
        assert len(result.matches) >= 2
        for match in result.matches:
            assert match.matched_keyword
            assert match.language == "en"
            assert match.utterance_id in {u.id for u in utterances}

    def test_detects_spanish_greeting(self) -> None:
        session_id = uuid.uuid4()
        utterances = [FakeUtterance(uuid.uuid4(), 0, "Buenos dias a todos", 0, 1000)]

        result = detect_greetings(session_id, utterances)

        assert result.has_greeting is True
        assert result.matches[0].language == "es"

    def test_no_greeting_found(self) -> None:
        session_id = uuid.uuid4()
        utterances = [FakeUtterance(uuid.uuid4(), 0, "The derivative of x squared is 2x", 0, 1000)]

        result = detect_greetings(session_id, utterances)

        assert result.has_greeting is False
        assert result.matches == []
        assert result.session_start_boundary is None

    def test_session_start_boundary_is_first_match_seq(self) -> None:
        session_id = uuid.uuid4()
        utterances = [
            FakeUtterance(uuid.uuid4(), 0, "Let's begin", 0, 1000),
            FakeUtterance(uuid.uuid4(), 1, "Good afternoon class", 1000, 2000),
        ]

        result = detect_greetings(session_id, utterances)

        assert result.session_start_boundary == 1


@pytest.mark.integration
class TestT332GreetingNeverMutatesUtteranceRows:
    """Explicit negative assertion: greeting detection must never write to
    speaker_tag, is_relevant, or filter_reason. Proven by snapshotting real
    DB rows before/after and diffing (spec §7 T33.2)."""

    async def test_no_utterance_columns_mutated(self, db_session: AsyncSession) -> None:
        user = User(
            email=f"t-{uuid.uuid4().hex[:8]}@example.com", hashed_password="h", is_active=True
        )
        db_session.add(user)
        await db_session.flush()
        provisioner = PartitionProvisioner()
        subject = await provisioner.provision_subject(
            db_session, user.id, name=f"Physics {uuid.uuid4().hex[:8]}"
        )
        session_obj = Session(subject_id=subject.id, session_type="content")
        db_session.add(session_obj)
        await db_session.flush()

        utt = Utterance(
            subject_id=subject.id,
            session_id=session_obj.id,
            seq=0,
            start_ms=0,
            end_ms=1000,
            text="Good morning everyone, welcome to class",
            embed_model_ver="qwen3-0.6b-v1",
            speaker_tag=None,
            is_relevant=None,
            filter_reason=None,
        )
        db_session.add(utt)
        await db_session.flush()

        before = (
            await db_session.execute(select(Utterance).where(Utterance.id == utt.id))
        ).scalar_one()
        snapshot = {
            "speaker_tag": before.speaker_tag,
            "is_relevant": before.is_relevant,
            "filter_reason": before.filter_reason,
        }

        fake = FakeUtterance(utt.id, utt.seq, utt.text, utt.start_ms, utt.end_ms)
        result = detect_greetings(session_obj.id, [fake])
        assert result.has_greeting is True

        after = (
            await db_session.execute(
                select(Utterance).where(Utterance.id == utt.id, Utterance.subject_id == subject.id)
            )
        ).scalar_one()

        assert after.speaker_tag == snapshot["speaker_tag"]
        assert after.is_relevant == snapshot["is_relevant"]
        assert after.filter_reason == snapshot["filter_reason"]
