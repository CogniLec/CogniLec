"""Tests for the S19 ASR worker (T19.1-T19.7).

ENVIRONMENT CAVEATS (read before trusting any pass/fail here):

1. GPU: the NVIDIA driver issue that originally blocked GPU tests here is
   resolved (docs/gaps.md #3, fixed by a host reboot) and GPU access is
   confirmed working across all 3 machines in the current deployment
   (docs/gaps.md #29-#31). These tests still use a small faster-whisper
   model (`tiny.en`, CPU, compute_type="int8") instead of the production
   `large-v3`/`large-v3-turbo` at production quantization, deliberately -
   not because of a driver problem, but because the production weights
   aren't cached in this test environment and downloading them per test
   run would be slow/flaky. This proves the transcription -> persistence
   -> state-machine mechanism works; it does NOT verify production-model
   accuracy or GPU real-time-factor.

2. T19.1 (WER within tolerance of the S06 benchmark): the real S06 held-out
   benchmark does not exist yet - S04's real audio corpus has 5 real
   recordings (docs/gaps.md #27) but with placeholder room/device/subject/
   consent metadata, and S05's hand-transcription (ground-truth WER
   labels) hasn't started, so there is no real number to compare against.
   `test_wer_benchmark` below therefore validates the WER *computation
   mechanism* (reusing src/ml/asr/wer.py from S06) against a synthetic
   reference/hypothesis pair with a hand-countable edit distance, NOT a
   real production-benchmark comparison. Real S06 benchmark validation is
   blocked on S05 hand-labelling and finishing S04's metadata, not on any
   GPU/driver issue (resolved) or diarisation model access (resolved,
   docs/gaps.md #31).

3. T19.6 (RTF < 1.0 "on GPU"): run on CPU with the tiny model instead. The
   actual measured RTF is asserted and printed; this does not prove the
   production model hits RTF<1.0 on GPU.

Audio fixture: tests/fixtures/audio/sample_speech.wav is the public-domain
smoke-test sample "she had your dark suit..." (LDC93S1, distributed with
Mozilla DeepSpeech's test assets) - real recorded speech, so transcription
produces genuine non-trivial text and word timestamps.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from src.db.models.session import SessionStatus
from src.db.models.user import User
from src.db.partitions.provisioner import PartitionProvisioner
from src.db.repositories.session_repo import SessionRepository
from src.db.repositories.utterance_repo import UtteranceRepository
from src.ml.asr.wer import compute_wer
from src.services.asr.service import FasterWhisperASRService
from src.services.nfr_r3_gate import NFR_R3_Gate
from src.services.storage.models import BucketName
from src.workers.asr_worker import ASRWorker
from tests.conftest import DATABASE_URL

pytestmark = pytest.mark.integration

FIXTURE_WAV = Path(__file__).parent / "fixtures" / "audio" / "sample_speech.wav"


class FakeStorageClient:
    """Returns a fixed WAV file for any get_object call - avoids a MinIO dependency."""

    def __init__(self, wav_bytes: bytes) -> None:
        self._wav_bytes = wav_bytes
        self.calls: list[tuple[BucketName, str]] = []

    async def get_object(self, bucket: BucketName, key: str) -> bytes:
        self.calls.append((bucket, key))
        return self._wav_bytes


class FakeStreamProducer:
    """No-op stand-in for ValkeyStreamProducer.xack (worker only needs xack here)."""

    def __init__(self) -> None:
        self.acked: list[tuple[str, str, str]] = []

    async def xack(self, stream: str, group: str, message_id: str) -> None:
        self.acked.append((stream, group, message_id))


@pytest.fixture(scope="module")
def asr_service() -> FasterWhisperASRService:
    """A real faster-whisper model (tiny.en, CPU, int8) - see module docstring."""
    return FasterWhisperASRService(
        model_name="tiny.en",
        compute_type="int8",
        device="cpu",
        beam_size=5,
        language="en",
        embed_model_ver="qwen3-0.6b-v1",
        word_timestamps=True,
        alignment_model=None,
        alignment_enabled=False,
    )


@pytest.fixture
def session_factory() -> Any:
    """A fresh sessionmaker bound to the test DB, separate from db_session so
    the worker's own commit()s are real and independently observable."""
    engine = create_async_engine(DATABASE_URL, echo=False)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _create_subject_and_session(db_session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    """Create a user, a provisioned subject (with utterances partition), and a
    session in RECORDING status. Returns (subject_id, session_id)."""
    user = User(
        email=f"asr-test-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="hashed",
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()

    provisioner = PartitionProvisioner()
    subject = await provisioner.provision_subject(db_session, user.id, name="ASR Test Subject")

    session_repo = SessionRepository(db_session)
    session_obj = await session_repo.create(subject.id, "content")
    await session_repo.update_status(session_obj, SessionStatus.RECORDING)
    await db_session.commit()

    return subject.id, session_obj.id


class TestWERBenchmark:
    """T19.1 - WER computation mechanism (NOT a real S06 benchmark comparison).

    The genuine held-out S06 benchmark cannot be evaluated: S04's real audio
    corpus is incomplete and no S06 MLflow bake-off run has ever passed. This
    test instead proves compute_wer() (reused from S06's src/ml/asr/wer.py)
    is correct against a synthetic reference/hypothesis pair with a known,
    hand-countable edit distance - i.e. mechanism-only, honestly labeled.
    """

    def test_wer_computation_mechanism(self) -> None:
        reference = "the quick brown fox jumps over the lazy dog"
        # One substitution ("fast" for "quick") out of 9 words -> WER = 1/9.
        hypothesis = "the fast brown fox jumps over the lazy dog"
        wer = compute_wer(reference, hypothesis)
        assert wer == pytest.approx(1 / 9, abs=1e-6)

    def test_wer_identical_is_zero(self) -> None:
        text_ = "she had your dark suit in greasy wash water all year"
        assert compute_wer(text_, text_) == 0.0

    @pytest.mark.skip(
        reason=(
            "Blocked: no real S06 held-out benchmark exists yet (S04 audio corpus "
            "incomplete, no passing S06 MLflow bake-off run). Cannot honestly compare "
            "against a real benchmark number - see module docstring."
        )
    )
    def test_wer_within_tolerance_of_s06_benchmark(self) -> None:
        raise NotImplementedError


class TestWordTimestamps:
    """T19.2 - word-level timestamps present and monotonically increasing."""

    def test_word_timestamps_monotonic(self, asr_service: FasterWhisperASRService) -> None:
        import soundfile as sf

        audio, sr = sf.read(str(FIXTURE_WAV), dtype="float32")
        result = asr_service.transcribe_chunk(
            audio, sr, uuid.uuid4(), uuid.uuid4(), sequence_start=0
        )

        assert len(result.utterances) > 0
        for utt in result.utterances:
            assert len(utt.words) > 0
            assert utt.start_ms < utt.end_ms
            prev_end = -1
            for word in utt.words:
                assert word.start_ms < word.end_ms
                assert word.start_ms >= prev_end
                assert 0.0 <= word.confidence <= 1.0
                prev_end = word.end_ms

    def test_transcribed_text_is_nontrivial(self, asr_service: FasterWhisperASRService) -> None:
        import soundfile as sf

        audio, sr = sf.read(str(FIXTURE_WAV), dtype="float32")
        result = asr_service.transcribe_chunk(
            audio, sr, uuid.uuid4(), uuid.uuid4(), sequence_start=0
        )
        full_text = " ".join(u.text for u in result.utterances).lower()
        # Known content of the LDC93S1 smoke-test sample.
        assert "suit" in full_text or "water" in full_text


class TestUtterancePersistence:
    """T19.3 - utterances persisted with confidence, session/subject, embed_model_ver."""

    async def test_utterance_persistence(
        self, db_session: AsyncSession, asr_service: FasterWhisperASRService
    ) -> None:
        subject_id, session_id = await _create_subject_and_session(db_session)

        import soundfile as sf

        audio, sr = sf.read(str(FIXTURE_WAV), dtype="float32")
        result = asr_service.transcribe_chunk(audio, sr, session_id, subject_id, sequence_start=0)
        assert len(result.utterances) > 0

        repo = UtteranceRepository(db_session)
        rows = [
            {
                "session_id": u.session_id,
                "seq": u.sequence,
                "start_ms": u.start_ms,
                "end_ms": u.end_ms,
                "text": u.text,
                "asr_confidence": u.confidence,
                "words": [w.model_dump() for w in u.words],
                "speaker_tag": u.speaker_tag,
                "embed_model_ver": u.embed_model_ver,
            }
            for u in result.utterances
        ]
        inserted = await repo.bulk_insert(subject_id, rows)
        await db_session.commit()
        assert inserted == len(rows)

        persisted = await repo.get_by_session(subject_id, session_id)
        assert len(persisted) == len(rows)
        for row in persisted:
            assert row.session_id == session_id
            assert row.subject_id == subject_id
            assert row.embed_model_ver == "qwen3-0.6b-v1"
            assert row.asr_confidence is not None
            assert 0.0 <= row.asr_confidence <= 1.0
            assert isinstance(row.words, list)
            assert len(row.words) > 0


class TestSessionTranscribed:
    """T19.4 - session reaches transcribed only after the last utterance is committed."""

    async def test_session_transcribed_after_final_chunk(
        self,
        db_session: AsyncSession,
        session_factory: Any,
        asr_service: FasterWhisperASRService,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # This test is about T19.4's transcription-commit ordering only.
        # asr_worker.py synchronously awaits generate_study_materials right
        # after finalizing (src/workers/asr_worker.py:150) -- with no real
        # LLM router configured in this fixture environment, that call
        # genuinely fails (T5 exhausts all tiers) and, since the
        # docs/gaps.md #33g fix, now durably commits the session to
        # `failed`. That downstream pipeline is exercised by
        # tests/test_s47_process_session_flow.py; here it's a no-op so this
        # test can assert transcription's own status transition in
        # isolation, matching what it actually observed before that
        # unrelated failure state was (incorrectly) silently discarded.
        async def _noop_generate_study_materials(*args: object, **kwargs: object) -> int:
            return 0

        monkeypatch.setattr(
            "src.workers.asr_worker.generate_study_materials", _noop_generate_study_materials
        )

        subject_id, session_id = await _create_subject_and_session(db_session)

        wav_bytes = FIXTURE_WAV.read_bytes()
        worker = ASRWorker(
            session_factory,
            storage=FakeStorageClient(wav_bytes),
            stream=FakeStreamProducer(),
            asr_service=asr_service,
        )

        # Before processing: still recording.
        session_repo = SessionRepository(db_session)
        before = await session_repo.get_or_raise(session_id)
        assert before.status == SessionStatus.RECORDING

        await worker.process_message(
            "1-0",
            {
                "session_id": str(session_id),
                "sequence": "0",
                "object_key": "irrelevant",
                "has_speech": "true",
                "speech_ratio": "0.9",
                "final": "true",
            },
        )

        db_session.expire_all()  # worker committed via a separate DB session/connection
        after = await session_repo.get_or_raise(session_id)
        assert after.status == SessionStatus.TRANSCRIBED

        repo = UtteranceRepository(db_session)
        persisted = await repo.get_by_session(subject_id, session_id)
        assert len(persisted) > 0

    async def test_not_transcribed_without_final_flag(
        self,
        db_session: AsyncSession,
        session_factory: Any,
        asr_service: FasterWhisperASRService,
    ) -> None:
        _subject_id, session_id = await _create_subject_and_session(db_session)

        wav_bytes = FIXTURE_WAV.read_bytes()
        worker = ASRWorker(
            session_factory,
            storage=FakeStorageClient(wav_bytes),
            stream=FakeStreamProducer(),
            asr_service=asr_service,
        )

        await worker.process_message(
            "1-0",
            {
                "session_id": str(session_id),
                "sequence": "0",
                "object_key": "irrelevant",
                "has_speech": "true",
                "speech_ratio": "0.9",
                "final": "false",
            },
        )

        db_session.expire_all()
        session_repo = SessionRepository(db_session)
        session_obj = await session_repo.get_or_raise(session_id)
        assert session_obj.status == SessionStatus.RECORDING


class TestCrashRecovery:
    """T19.5 - restart does not reprocess chunks that already have utterances."""

    async def test_crash_recovery_skips_processed_chunk(
        self,
        db_session: AsyncSession,
        session_factory: Any,
        asr_service: FasterWhisperASRService,
    ) -> None:
        subject_id, session_id = await _create_subject_and_session(db_session)

        wav_bytes = FIXTURE_WAV.read_bytes()
        storage = FakeStorageClient(wav_bytes)
        worker = ASRWorker(
            session_factory,
            storage=storage,
            stream=FakeStreamProducer(),
            asr_service=asr_service,
        )

        fields = {
            "session_id": str(session_id),
            "sequence": "0",
            "object_key": "irrelevant",
            "has_speech": "true",
            "speech_ratio": "0.9",
            "final": "false",
        }

        # First pass: transcribes and persists.
        await worker.process_message("1-0", fields)
        assert len(storage.calls) == 1

        db_session.expire_all()
        repo = UtteranceRepository(db_session)
        first_pass = await repo.get_by_session(subject_id, session_id)
        assert len(first_pass) > 0

        # Simulated restart: same chunk arrives again (e.g. re-delivered
        # after a crash before ack). Storage must NOT be hit again, and the
        # utterance set must be unchanged.
        await worker.process_message("1-1", fields)
        assert len(storage.calls) == 1, "chunk was reprocessed after crash recovery should skip it"

        db_session.expire_all()
        second_pass = await repo.get_by_session(subject_id, session_id)
        assert len(second_pass) == len(first_pass)


class TestRealTimeFactor:
    """T19.6 - real-time factor. Measured on CPU with a tiny model (no GPU here);
    see module docstring for why this doesn't prove production GPU RTF."""

    def test_real_time_factor_cpu_tiny_model(self, asr_service: FasterWhisperASRService) -> None:
        import soundfile as sf

        audio, sr = sf.read(str(FIXTURE_WAV), dtype="float32")
        result = asr_service.transcribe_chunk(
            audio, sr, uuid.uuid4(), uuid.uuid4(), sequence_start=0
        )

        print(
            f"\n[T19.6] measured RTF={result.real_time_factor:.4f} "
            f"(processing_time_ms={result.processing_time_ms}, "
            f"duration_ms={result.total_duration_ms}, model=tiny.en/cpu/int8 - "
            f"NOT production large-v3/GPU)"
        )
        assert result.real_time_factor < 1.0


class TestNFRR3Gate:
    """T19.7 - downstream flow rejected if session status is not transcribed."""

    async def test_gate_raises_for_recording_session(self, db_session: AsyncSession) -> None:
        _subject_id, session_id = await _create_subject_and_session(db_session)

        gate = NFR_R3_Gate(SessionRepository(db_session))
        with pytest.raises(ValueError, match="NFR-R3 violated"):
            await gate.assert_transcribed(session_id)

    async def test_gate_passes_for_transcribed_session(self, db_session: AsyncSession) -> None:
        _subject_id, session_id = await _create_subject_and_session(db_session)

        session_repo = SessionRepository(db_session)
        session_obj = await session_repo.get_or_raise(session_id)
        await session_repo.update_status(session_obj, SessionStatus.TRANSCRIBED)
        await db_session.commit()

        gate = NFR_R3_Gate(session_repo)
        assert await gate.assert_transcribed(session_id) is True


class TestReconciliationSweep:
    """Recovers a `recording` session that was never finalized (e.g. the
    tab closed/crashed before Stop) -- run_reconciliation_sweep must both
    transition it to transcribed AND trigger the same materials-generation
    path a normal `is_final` chunk would."""

    async def test_sweep_finalizes_stale_session_and_triggers_materials(
        self,
        db_session: AsyncSession,
        session_factory: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from datetime import UTC, datetime, timedelta

        from src.db.models.utterance import Utterance

        subject_id, session_id = await _create_subject_and_session(db_session)
        old = datetime.now(UTC) - timedelta(hours=25)
        session_obj = await SessionRepository(db_session).get_or_raise(session_id)
        session_obj.created_at = old
        db_session.add(
            Utterance(
                subject_id=subject_id,
                session_id=session_id,
                seq=0,
                start_ms=0,
                end_ms=1000,
                text="real content",
                embed_model_ver="v1",
                created_at=old + timedelta(minutes=1),
            )
        )
        await db_session.commit()

        calls: list[tuple[Any, Any]] = []

        async def fake_generate(session_id: Any, subject_id: Any, db: Any) -> int:
            calls.append((session_id, subject_id))
            return 0

        monkeypatch.setattr("src.workers.asr_worker.generate_study_materials", fake_generate)

        # asr_service unused by this sweep path -- pass a stub so the
        # worker doesn't load a real ASR model just to construct.
        worker = ASRWorker(session_factory, stream=FakeStreamProducer(), asr_service=object())
        await worker.run_reconciliation_sweep()

        # Membership, not exact equality: run_reconciliation_sweep also now
        # sweeps stale `transcribed` sessions (session_reconciliation.py),
        # which can legitimately pick up unrelated leftover rows from other
        # tests sharing this same integration test DB.
        assert (session_id, subject_id) in calls
        db_session.expire_all()
        after = await SessionRepository(db_session).get_or_raise(session_id)
        assert after.status == SessionStatus.TRANSCRIBED
