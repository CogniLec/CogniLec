"""S20 T20.5 - End-to-end ingestion spine gate test.

============================================================================
HONESTY STATEMENT - READ BEFORE TRUSTING ANY PASS HERE (this is a HARD GATE)
============================================================================

The S20 spec frames T20.5 as a project HARD GATE: "all downstream blocks
(S21+) may begin ONLY after T20.5 passes" on a real 60-minute lecture
recording, with a working GPU and real multi-speaker diarisation. THAT GATE
IS NOT GENUINELY CLOSED BY THIS TEST FILE. Specifically, three things this
environment cannot provide, none of them fixable from inside this task:

1. GPU: nvidia-smi fails here (driver/library version mismatch). No CUDA
   device is usable, so real production-model ASR/diarisation RTF cannot be
   measured.
2. Real audio corpus: S04's real lecture corpus is incomplete (6 of 8-10
   sessions recorded, per tests/test_asr_worker.py's module docstring) -
   there is no real 60-minute lecture fixture with known ground truth.
3. pyannote.audio: not installed (deliberately - see tests/test_diarisation.py's
   module docstring); its pretrained model is HuggingFace-gated and no
   HF_TOKEN/HUGGINGFACE_TOKEN is configured in .env here.

What this test DOES genuinely verify: the full mechanical ingestion spine -
create session (real API) -> upload a short chunk (real MinIO, real API) ->
preprocess (real S17 chain: resample/loudnorm/VAD, real ffmpeg) -> ASR (real
S19 faster-whisper, tiny.en model, CPU) -> diarisation (S20 worker, no real
pyannote backend - single-speaker fallback tags SPK_A) -> verifies the
resulting DB-1 row set matches every field the spec's T20.5 acceptance list
requires (text, timestamps, confidence, words, session_id, subject_id,
embed_model_ver, speaker_tag, session status, audio_quality is settable).

This proves the WIRING is correct end to end. It does NOT prove:
- production-model transcription accuracy (tiny.en vs large-v3-turbo)
- RTF < 2.0 "for a full 60-minute session" (only a ~5s fixture is measured;
  that specific RTF assertion is marked xfail/skip below, not asserted as
  if it were the real 60-minute number)
- real diarisation detecting 3+ distinct real speakers (mono, single-speaker
  fixture; no pyannote backend wired in)

CONCLUSION: T20.5 as literally specified (real 60-min lecture, GPU,
real pyannote) is NOT PASSED and cannot be honestly claimed to pass in this
environment. Downstream blocks (S21+) should NOT be treated as unblocked on
the strength of this test alone - see the final report for the explicit gate
status.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from src.api.dependencies.auth import get_current_user
from src.api.dependencies.database import get_db_session
from src.api.dependencies.settings import get_app_settings
from src.api.dependencies.valkey import get_valkey_stream
from src.api.routes.chunks import router as chunks_router
from src.core.config import Settings
from src.db.models.session import SessionStatus
from src.db.models.user import User
from src.db.partitions.provisioner import PartitionProvisioner
from src.db.repositories.session_repo import SessionRepository
from src.db.repositories.utterance_repo import UtteranceRepository
from src.services.asr.service import FasterWhisperASRService
from src.services.diarisation.models import DiarisationState
from src.services.diarisation.worker import DiarisationWorker
from src.services.storage.client import StorageClient
from src.services.storage.models import BucketName
from src.services.valkey_stream import ValkeyStreamProducer
from src.workers.asr_worker import ASRWorker
from src.workers.preprocessing_worker import PreprocessingWorker
from tests.conftest import DATABASE_URL

pytestmark = pytest.mark.integration

VALKEY_URL = "redis://localhost:6379/0"
FIXTURE_WAV = Path(__file__).parent / "fixtures" / "audio" / "sample_speech.wav"


def _settings() -> Settings:
    return Settings(MINIO_ENDPOINT="localhost:9000", VALKEY_URL=VALKEY_URL)


def _build_app(
    db_session: AsyncSession, stream: ValkeyStreamProducer, user_id: uuid.UUID
) -> FastAPI:
    app = FastAPI()
    app.include_router(chunks_router, prefix="/api/v1")

    async def _override_db() -> Any:
        yield db_session
        # Mirror src/api/dependencies/database.py's real get_db_session, which
        # commits after a successful request. Without this, the chunk-upload
        # endpoint's `created->recording` status UPDATE stays open on this
        # session's transaction forever (never committed), row-locking the
        # sessions row and deadlocking the ASR worker's separate
        # session_factory connection when it later tries to update the same
        # row in _finalize_session.
        await db_session.commit()

    async def _override_stream() -> ValkeyStreamProducer:
        return stream

    def _override_settings() -> Settings:
        return _settings()

    async def _override_user() -> dict[str, object]:
        return {"id": str(user_id), "email": "gate-test@example.com"}

    app.dependency_overrides[get_db_session] = _override_db
    app.dependency_overrides[get_valkey_stream] = _override_stream
    app.dependency_overrides[get_app_settings] = _override_settings
    app.dependency_overrides[get_current_user] = _override_user
    return app


@pytest.fixture
async def valkey() -> Any:
    client = Redis.from_url(VALKEY_URL, decode_responses=True)
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()


@pytest.fixture
async def stream(valkey: Redis) -> ValkeyStreamProducer:
    return ValkeyStreamProducer(settings=_settings(), client=valkey)


@pytest.fixture
def session_factory() -> Any:
    engine = create_async_engine(DATABASE_URL, echo=False)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(scope="module")
def asr_service() -> FasterWhisperASRService:
    """Tiny CPU model - see honesty statement above and test_asr_worker.py."""
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


class TestIngestionSpineE2E:
    """T20.5 - mechanical ingestion-spine gate test. See module docstring:
    this is NOT the real 60-minute-lecture / GPU / pyannote gate."""

    async def test_ingestion_spine_e2e(
        self,
        db_session: AsyncSession,
        stream: ValkeyStreamProducer,
        valkey: Redis,
        session_factory: Any,
        asr_service: FasterWhisperASRService,
    ) -> None:
        # --- 1. Create session (real API layer, real Postgres) ---
        user = User(
            email=f"gate-test-{uuid.uuid4().hex[:8]}@example.com",
            hashed_password="hashed",
            is_active=True,
        )
        db_session.add(user)
        await db_session.flush()
        provisioner = PartitionProvisioner()
        subject = await provisioner.provision_subject(db_session, user.id, name="Gate Test Subject")
        subject_id = subject.id

        session_repo = SessionRepository(db_session)
        session_obj = await session_repo.create(subject_id, "content")
        await db_session.commit()
        session_id = session_obj.id

        # Consumer groups must exist (start() creates them at "$") BEFORE any
        # message is published, or the group's cursor starts after it.
        settings = _settings()
        storage = StorageClient(settings)
        preprocessing_worker = PreprocessingWorker(
            settings=settings, storage=storage, stream=stream
        )
        await preprocessing_worker.start()
        asr_worker = ASRWorker(
            session_factory,
            settings=settings,
            storage=storage,
            stream=stream,
            asr_service=asr_service,
        )
        await asr_worker.start()

        # --- 2/3. Upload chunk via the real chunks API + real MinIO ---
        wav_bytes = FIXTURE_WAV.read_bytes()
        app = _build_app(db_session, stream, user.id)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            files = {"chunk": ("chunk.opus", wav_bytes, "audio/wav")}
            form = {"sequence": "0", "timestamp_ms": "0", "duration_ms": "5000"}
            response = await client.post(
                f"/api/v1/sessions/{session_id}/chunks", data=form, files=files
            )
        assert response.status_code == 200
        upload_body = response.json()
        assert upload_body["status"] == "stored"

        # --- 4. Preprocess (real S17 chain via real Valkey stream + MinIO) ---
        processed_count = await preprocessing_worker.run_once(count=5, block_ms=2000)
        assert processed_count == 1

        # --- 5. ASR (real S19 faster-whisper worker, tiny.en/CPU) ---
        # Mark the (only) processed chunk final so the session transitions.
        entries = await valkey.xrange("audio.processed")
        assert len(entries) == 1
        msg_id, fields = entries[0]
        fields = dict(fields)
        fields["final"] = "true"
        await asr_worker.process_message(msg_id, fields)

        db_session.expire_all()
        after_asr = await session_repo.get_or_raise(session_id)
        assert after_asr.status == SessionStatus.TRANSCRIBED

        utterance_repo = UtteranceRepository(db_session)
        utterances = await utterance_repo.get_by_session(subject_id, session_id)
        assert len(utterances) > 0, "ASR produced no utterances from the fixture audio"

        # --- 6. Diarisation (S20; no real pyannote backend - see honesty
        # statement - single-speaker fallback: all utterances -> SPK_A) ---
        diarisation_worker = DiarisationWorker(session_factory, settings=settings, backend=None)
        diarisation_result = await diarisation_worker.process_session(
            session_id, enable_diarisation=True
        )
        assert diarisation_result.state == DiarisationState.TAGGED

        # Manually set audio_quality (S18 normally computes this from the
        # preprocessing chain's SNR metrics; asserting the field is settable
        # and persisted is what T20.5 requires here).
        session_obj = await session_repo.get_or_raise(session_id)
        await session_repo.update_audio_quality(session_obj, 0.85)
        await db_session.commit()

        # --- 7. Verify complete transcript in DB-1 (T20.5 acceptance list) ---
        db_session.expire_all()
        final_session = await session_repo.get_or_raise(session_id)
        assert final_session.status == SessionStatus.TRANSCRIBED
        assert final_session.audio_quality == pytest.approx(0.85)

        final_utterances = await utterance_repo.get_by_session(subject_id, session_id)
        assert len(final_utterances) > 0
        for utt in final_utterances:
            assert utt.session_id == session_id
            assert utt.subject_id == subject_id
            assert utt.text
            assert utt.start_ms < utt.end_ms
            assert utt.asr_confidence is not None
            assert 0.0 <= utt.asr_confidence <= 1.0
            assert isinstance(utt.words, list)
            assert len(utt.words) > 0
            assert utt.embed_model_ver == "qwen3-0.6b-v1"
            assert utt.speaker_tag == "SPK_A"  # single-speaker fallback tag

        # Cleanup uploaded/processed MinIO objects created by this test.
        await storage.delete_object(BucketName.AUDIO, upload_body["stored_key"])
        processed_key = f"{session_id}/processed/00000.wav"
        await storage.delete_object(BucketName.AUDIO, processed_key)

    @pytest.mark.skip(
        reason=(
            "Blocked: RTF<2.0 'for a full 60-minute session' cannot be honestly "
            "measured - there is no real 60-minute lecture fixture (S04 corpus "
            "incomplete) and no working GPU (nvidia-smi driver/library mismatch) "
            "on this host, so the production model/hardware combination the spec "
            "means is not available. test_ingestion_spine_e2e above measures "
            "correctness of the pipeline wiring on a ~5s fixture only, not RTF "
            "at 60-minute/GPU scale."
        )
    )
    def test_rtf_under_2_for_full_60_minute_session(self) -> None:
        raise NotImplementedError
