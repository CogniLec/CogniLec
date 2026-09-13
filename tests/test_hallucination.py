"""Tests for the S22 hallucination detection (T22.1-T22.5).

T22.1 and T22.2 require feeding real silence/repeated-phrase audio through
primary ASR to produce the canonical hallucinated utterances - we don't run
a real ASR model in this environment (see tests/test_asr_worker.py's
documented GPU/driver constraint). Instead we exercise the exact detector
behaviour the spec describes against synthetic utterances shaped like the
real Whisper failure modes it names (silence -> agreement=0.0 text output;
a deliberately repeated phrase). This tests the detection MECHANISM
faithfully; it does not validate the upstream ASR's actual hallucination
rate on real audio, which is what T22.1/T22.2 as literally specified would
require.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.models.user import User
from src.db.partitions.provisioner import PartitionProvisioner
from src.db.repositories.session_repo import SessionRepository
from src.db.repositories.utterance_repo import UtteranceRepository
from src.ml.hallucination import (
    CrossModelDetector,
    HallucinationConfig,
    HallucinationDetector,
    RepetitionDetector,
    VADContradictionDetector,
    VADRegion,
)
from src.workers.hallucination_worker import HallucinationWorker

pytestmark = pytest.mark.integration


@dataclass
class _Utt:
    text: str
    start_ms: int
    end_ms: int
    asr_agreement: float | None


class TestCrossModelDetector:
    def test_fires_below_threshold_with_text(self) -> None:
        detector = CrossModelDetector(agreement_threshold=0.5)
        fired, _ = detector.detect(_Utt("hallucinated text", 0, 1000, 0.0))
        assert fired is True

    def test_skips_when_agreement_is_none(self) -> None:
        detector = CrossModelDetector(agreement_threshold=0.5)
        fired, detail = detector.detect(_Utt("some text", 0, 1000, None))
        assert fired is False
        assert "skipped" in detail

    def test_does_not_fire_above_threshold(self) -> None:
        detector = CrossModelDetector(agreement_threshold=0.5)
        fired, _ = detector.detect(_Utt("agreeing text", 0, 1000, 0.9))
        assert fired is False


class TestRepetitionDetector:
    def test_t22_2_deliberate_repetition_fires(self) -> None:
        """T22.2: 'the process is the process is the process is the process'."""
        detector = RepetitionDetector(max_repeat_ngram=3, max_repeat_count=3)
        text = "the process is the process is the process is the process"
        fired, detail = detector.detect(_Utt(text, 0, 5000, None))
        assert fired is True
        assert detail["count"] >= 3

    def test_normal_speech_does_not_fire(self) -> None:
        detector = RepetitionDetector(max_repeat_ngram=3, max_repeat_count=3)
        text = "welcome to today's lecture on machine learning fundamentals and applications"
        fired, _ = detector.detect(_Utt(text, 0, 5000, None))
        assert fired is False

    def test_tolerates_intentional_double_repetition(self) -> None:
        """False-positive guard: 'any questions? any questions?' (2x) must not fire."""
        detector = RepetitionDetector(max_repeat_ngram=3, max_repeat_count=3)
        fired, _ = detector.detect(_Utt("any questions any questions", 0, 2000, None))
        assert fired is False


class TestVADContradictionDetector:
    def test_fires_when_utterance_mostly_in_silence(self) -> None:
        detector = VADContradictionDetector(vad_margin_ms=0, min_utterance_length_ms=500)
        regions = [VADRegion(start_ms=0, end_ms=5000, is_speech=False)]
        fired, detail = detector.detect(_Utt("phantom text", 1000, 3000, None), regions)
        assert fired is True
        assert detail["fraction"] > 0.5

    def test_does_not_fire_when_in_speech_region(self) -> None:
        detector = VADContradictionDetector(vad_margin_ms=0, min_utterance_length_ms=500)
        regions = [VADRegion(start_ms=0, end_ms=5000, is_speech=True)]
        fired, _ = detector.detect(_Utt("real text", 1000, 3000, None), regions)
        assert fired is False

    def test_skips_when_no_vad_regions(self) -> None:
        detector = VADContradictionDetector()
        fired, detail = detector.detect(_Utt("text", 1000, 3000, None), None)
        assert fired is False
        assert "skipped" in detail

    def test_skips_short_utterances(self) -> None:
        detector = VADContradictionDetector(min_utterance_length_ms=500)
        regions = [VADRegion(start_ms=0, end_ms=5000, is_speech=False)]
        fired, detail = detector.detect(_Utt("hi", 1000, 1100, None), regions)
        assert fired is False
        assert "skipped" in detail


class TestHallucinationDetectorOrchestration:
    def test_t22_1_silence_hallucination_flagged(self) -> None:
        """T22.1 mechanism: text emitted where secondary agreement is 0.0 and
        VAD marked the region as silence -> flagged is_hallucination=True."""
        detector = HallucinationDetector(HallucinationConfig())
        regions = [VADRegion(start_ms=0, end_ms=60_000, is_speech=False)]
        utt = _Utt("thank you thank you thank you", 0, 3000, 0.0)
        result = detector.detect(utt, regions)
        assert result.is_hallucination is True
        assert result.filter_reason is not None
        assert result.filter_reason.startswith("asr_hallucination")

    def test_t22_2_repetition_filter_reason(self) -> None:
        detector = HallucinationDetector(HallucinationConfig())
        text = "the process is the process is the process is the process"
        utt = _Utt(text, 0, 5000, 0.9)
        result = detector.detect(utt, None)
        assert result.is_hallucination is True
        assert result.filter_reason == "asr_hallucination_repetition"

    def test_t22_3_false_positive_rate_under_2_percent_on_real_speech(self) -> None:
        """T22.3: 100 synthetic 'genuine lecture content' utterances (varied,
        non-repetitive, high agreement, inside VAD-speech regions) - at most
        2/100 may be flagged."""
        detector = HallucinationDetector(HallucinationConfig())
        speech_region = [VADRegion(start_ms=0, end_ms=1_000_000, is_speech=True)]
        topics = [
            "gradient descent minimizes the loss function iteratively",
            "neural networks learn hierarchical feature representations",
            "the transformer architecture relies on self attention",
            "overfitting occurs when a model memorizes training data",
            "cross validation helps estimate generalization performance",
        ]
        flagged = 0
        for i in range(100):
            text = f"{topics[i % len(topics)]} in example number {i}"
            utt = _Utt(text, i * 5000, i * 5000 + 4000, 0.85)
            result = detector.detect(utt, speech_region)
            if result.is_hallucination:
                flagged += 1
        assert flagged / 100 < 0.02

    def test_detector_failure_isolation(self) -> None:
        """One detector raising must not prevent the others from running."""

        class _BrokenUtt:
            text = "text"
            start_ms = 0
            end_ms = 1000
            asr_agreement = "not-a-float"  # triggers a comparison error

        detector = HallucinationDetector(HallucinationConfig())
        result = detector.detect(_BrokenUtt(), None)
        assert "cross_model" in result.details


class TestHallucinationWorkerPersistence:
    async def test_t22_4_flagged_utterance_is_soft_deleted_not_removed(
        self, db_session: AsyncSession
    ) -> None:
        """T22.4: flagged row exists, is_relevant=false, filter_reason set."""
        user = User(
            email=f"test-{uuid.uuid4().hex[:8]}@example.com", hashed_password="h", is_active=True
        )
        db_session.add(user)
        await db_session.flush()
        provisioner = PartitionProvisioner()
        subject = await provisioner.provision_subject(db_session, user.id, name="Test Subject")
        session_repo = SessionRepository(db_session)
        session_obj = await session_repo.create(subject.id)
        await db_session.commit()

        utterance_repo = UtteranceRepository(db_session)
        text = "the process is the process is the process is the process"
        await utterance_repo.bulk_insert(
            subject.id,
            [
                {
                    "session_id": session_obj.id,
                    "seq": 0,
                    "start_ms": 0,
                    "end_ms": 5000,
                    "text": text,
                    "asr_confidence": 0.9,
                    "words": [],
                    "speaker_tag": None,
                    "embed_model_ver": "test-v1",
                }
            ],
        )
        await db_session.commit()

        class _Ctx:
            async def __aenter__(self):
                return db_session

            async def __aexit__(self, *exc):
                return False

        worker = HallucinationWorker(lambda: _Ctx())
        result = await worker.process_session(session_obj.id)
        assert result.flagged_count == 1

        rows = await utterance_repo.get_by_session(subject.id, session_obj.id)
        assert len(rows) == 1
        assert rows[0].is_relevant is False
        assert rows[0].filter_reason is not None
        assert rows[0].filter_reason.startswith("asr_hallucination")


@pytest.mark.skip(
    reason="T22.5 requires processing the full S04 real-speech audio corpus "
    "through the complete pipeline and recording the hallucination rate as a "
    "tracked MLflow metric. No MLflow tracking server is configured/running "
    "in this environment and S04's real audio corpus is not fed through a "
    "live ASR model here (see tests/test_asr_worker.py's GPU/driver caveat)."
)
def test_t22_5_hallucination_rate_recorded_as_metric() -> None:
    pass
