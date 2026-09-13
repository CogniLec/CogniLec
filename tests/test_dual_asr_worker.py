"""Tests for the S21 dual-ASR ensemble (T21.1, T21.3).

ENVIRONMENT / HONESTY CAVEATS:

No secondary ASR model (faster-whisper canary/parakeet backend per the S21
spec) is installed or downloadable in this environment - the same situation
documented for pyannote in tests/test_diarisation.py. Real dual-ASR
correlation against WER on the S05 labelled set (T21.2) and the 60-minute
performance budget (T21.4) cannot be genuinely exercised here and are marked
`@pytest.mark.skip` below with that reason.

What IS genuinely tested: the alignment (timestamp IoU), agreement scoring
(token-F1), and end-to-end persistence mechanism using a synthetic
`FakeSecondaryASRBackend` (T21.1), and graceful degradation when the backend
is unavailable/fails (T21.3).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.models.subject import Subject
from src.db.models.user import User
from src.db.partitions.provisioner import PartitionProvisioner
from src.db.repositories.session_repo import SessionRepository
from src.db.repositories.utterance_repo import UtteranceRepository
from src.workers.dual_asr_worker import (
    DualASRWorker,
    SecondaryUtterance,
    compute_agreement,
)

pytestmark = pytest.mark.integration


class FakeSecondaryASRBackend:
    def __init__(self, utterances: list[SecondaryUtterance]) -> None:
        self._utterances = utterances

    def transcribe(self, audio_path: str) -> list[SecondaryUtterance]:
        return self._utterances


class FailingSecondaryASRBackend:
    def transcribe(self, audio_path: str) -> list[SecondaryUtterance]:
        msg = "secondary model failed to load"
        raise RuntimeError(msg)


async def _create_user_subject_session(session: AsyncSession) -> tuple[Subject, uuid.UUID]:
    user = User(
        email=f"test-{uuid.uuid4().hex[:8]}@example.com", hashed_password="h", is_active=True
    )
    session.add(user)
    await session.flush()
    provisioner = PartitionProvisioner()
    subject = await provisioner.provision_subject(session, user.id, name="Test Subject")
    repo = SessionRepository(session)
    session_obj = await repo.create(subject.id)
    await session.commit()
    return subject, session_obj.id


def _make_session_factory(db_session: AsyncSession):
    class _Ctx:
        async def __aenter__(self):
            return db_session

        async def __aexit__(self, *exc):
            return False

    def factory():
        return _Ctx()

    return factory


class TestComputeAgreement:
    def test_identical_text_agreement_is_one(self) -> None:
        assert compute_agreement("hello world", "hello world") == pytest.approx(1.0)

    def test_disjoint_text_agreement_is_zero(self) -> None:
        assert compute_agreement("hello world", "goodbye moon") == pytest.approx(0.0)

    def test_partial_overlap_between_zero_and_one(self) -> None:
        score = compute_agreement("the quick brown fox", "the quick brown dog")
        assert 0.0 < score < 1.0


class TestDualASRWorkerT21:
    async def test_t21_1_every_utterance_gets_agreement_when_secondary_available(
        self, db_session: AsyncSession
    ) -> None:
        """T21.1: secondary model available -> every utterance gets a non-NULL
        agreement score in [0.0, 1.0] and utterances_aligned matches total."""
        subject, session_id = await _create_user_subject_session(db_session)
        utterance_repo = UtteranceRepository(db_session)

        rows = [
            {
                "session_id": session_id,
                "seq": i,
                "start_ms": i * 1000,
                "end_ms": i * 1000 + 900,
                "text": f"utterance number {i}",
                "asr_confidence": 0.9,
                "words": [],
                "speaker_tag": None,
                "embed_model_ver": "test-v1",
            }
            for i in range(5)
        ]
        await utterance_repo.bulk_insert(subject.id, rows)
        await db_session.commit()

        secondary = [
            SecondaryUtterance(
                text=f"utterance number {i}", start_ms=i * 1000, end_ms=i * 1000 + 900
            )
            for i in range(5)
        ]
        worker = DualASRWorker(
            _make_session_factory(db_session), backend=FakeSecondaryASRBackend(secondary)
        )
        result = await worker.process_session(session_id, audio_path="/fake/audio.wav")

        assert result.utterances_total == 5
        assert result.utterances_aligned == 5
        assert result.mean_agreement is not None
        assert 0.0 <= result.mean_agreement <= 1.0

        persisted = await utterance_repo.get_by_session(subject.id, session_id)
        assert all(u.asr_agreement is not None for u in persisted)
        assert all(0.0 <= u.asr_agreement <= 1.0 for u in persisted)

    async def test_t21_3_secondary_model_failure_degrades_gracefully(
        self, db_session: AsyncSession
    ) -> None:
        """T21.3: secondary model fails -> asr_agreement stays NULL for all
        utterances, no exception raised, pipeline completes."""
        subject, session_id = await _create_user_subject_session(db_session)
        utterance_repo = UtteranceRepository(db_session)
        await utterance_repo.bulk_insert(
            subject.id,
            [
                {
                    "session_id": session_id,
                    "seq": 0,
                    "start_ms": 0,
                    "end_ms": 900,
                    "text": "hello world",
                    "asr_confidence": 0.9,
                    "words": [],
                    "speaker_tag": None,
                    "embed_model_ver": "test-v1",
                }
            ],
        )
        await db_session.commit()

        worker = DualASRWorker(
            _make_session_factory(db_session), backend=FailingSecondaryASRBackend()
        )
        result = await worker.process_session(session_id, audio_path="/fake/audio.wav")

        assert result.degraded is True
        assert result.mean_agreement is None

        persisted = await utterance_repo.get_by_session(subject.id, session_id)
        assert all(u.asr_agreement is None for u in persisted)

    async def test_t21_3_no_backend_configured_degrades_gracefully(
        self, db_session: AsyncSession
    ) -> None:
        """No secondary backend configured at all (e.g. missing binary) ->
        same graceful-degradation contract, no exception."""
        subject, session_id = await _create_user_subject_session(db_session)
        utterance_repo = UtteranceRepository(db_session)
        await utterance_repo.bulk_insert(
            subject.id,
            [
                {
                    "session_id": session_id,
                    "seq": 0,
                    "start_ms": 0,
                    "end_ms": 900,
                    "text": "hello world",
                    "asr_confidence": 0.9,
                    "words": [],
                    "speaker_tag": None,
                    "embed_model_ver": "test-v1",
                }
            ],
        )
        await db_session.commit()

        worker = DualASRWorker(_make_session_factory(db_session), backend=None)
        result = await worker.process_session(session_id, audio_path="/fake/audio.wav")

        assert result.degraded is True
        persisted = await utterance_repo.get_by_session(subject.id, session_id)
        assert all(u.asr_agreement is None for u in persisted)


@pytest.mark.skip(
    reason="T21.2 requires the S05 labelled set with real primary+secondary ASR "
    "output to compute a Pearson correlation between agreement and WER. No "
    "secondary ASR model is installed/downloadable in this environment "
    "(same constraint as tests/test_diarisation.py for pyannote)."
)
def test_t21_2_agreement_correlates_negatively_with_wer() -> None:
    pass


@pytest.mark.skip(
    reason="T21.4 requires running a real secondary ASR model over a 60-minute "
    "(~600 utterance) session to measure wall-clock duration against the "
    "NFR-P3 budget. No secondary ASR model is installed in this environment."
)
def test_t21_4_dual_asr_completes_within_time_budget() -> None:
    pass
