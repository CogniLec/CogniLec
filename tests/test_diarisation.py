"""Tests for the S20 anonymous diarisation gate (T20.1-T20.4).

ENVIRONMENT / HONESTY CAVEATS (read before trusting any pass/fail here):

1. pyannote.audio is NOT installed in this environment and was deliberately
   not installed for this task. Even if it were, its pretrained
   `speaker-diarization-3.1` pipeline is gated on HuggingFace and requires an
   access token + license acceptance. `.env` here defines only `HF_HOME` (a
   cache directory) - no `HF_TOKEN`/`HUGGINGFACE_TOKEN` is configured - so
   the real model could not be downloaded even if the library were present.

2. GPU: this machine's NVIDIA driver is currently broken (nvidia-smi: driver/
   library version mismatch) - matching the S19 ASR worker's documented
   environment (see tests/test_asr_worker.py). Real pyannote diarisation
   also expects GPU for reasonable latency on long audio.

3. Consequently, T20.1 ("3+ distinct real speakers detected via pyannote on
   multi-speaker audio") CANNOT be genuinely exercised here. It is marked
   `@pytest.mark.skip` below with this reason, mirroring how S19's agent
   handled its own unmet WER-benchmark test. What IS genuinely tested here:
   the tag-assignment MECHANISM (segment -> utterance mapping, capping at
   SPK_A..SPK_E, UNKNOWN fallback) driven by a synthetic `FakeDiarisationBackend`
   standing in for pyannote's segment output, plus the fully-mechanical parts
   of the spec that do not require a real diarisation model at all: speaker
   tag persistence (T20.1's persistence half), the NFR-S4 schema/storage audit
   (T20.2), tag non-linkability (T20.3), and the disabled-mode fallback (T20.4).

T20.1, T20.2, T20.3, T20.4 test IDs below match the spec's test matrix.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from src.core.config import Settings
from src.db.models.session import SessionStatus
from src.db.models.user import User
from src.db.partitions.provisioner import PartitionProvisioner
from src.db.repositories.session_repo import SessionRepository
from src.db.repositories.utterance_repo import UtteranceRepository
from src.services.diarisation.models import DiarisationState, SpeakerTag
from src.services.diarisation.nfr_s4_audit import NFRS4Audit
from src.services.diarisation.worker import MAX_ASSIGNABLE_SPEAKERS, DiarisationWorker
from tests.conftest import DATABASE_URL

pytestmark = pytest.mark.integration


class _Segment:
    def __init__(self, start_ms: int, end_ms: int, speaker_index: int) -> None:
        self.start_ms = start_ms
        self.end_ms = end_ms
        self.speaker_index = speaker_index


class FakeDiarisationBackend:
    """Synthetic stand-in for a real pyannote.audio backend.

    Returns a fixed, pre-arranged list of speaker segments rather than
    running any real model - lets us test the tag-assignment mechanism
    (midpoint -> segment -> tag, capping, UNKNOWN fallback) without pyannote.
    """

    def __init__(self, segments: list[_Segment]) -> None:
        self._segments = segments
        self.calls: list[tuple[str, int]] = []

    def diarise(self, audio_path: str, max_speakers: int) -> list[_Segment]:
        self.calls.append((audio_path, max_speakers))
        return self._segments


@pytest.fixture
def session_factory() -> Any:
    engine = create_async_engine(DATABASE_URL, echo=False)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _create_subject_and_session(db_session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    user = User(
        email=f"diarisation-test-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="hashed",
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()

    provisioner = PartitionProvisioner()
    subject = await provisioner.provision_subject(
        db_session, user.id, name="Diarisation Test Subject"
    )

    session_repo = SessionRepository(db_session)
    session_obj = await session_repo.create(subject.id, "content")
    await session_repo.update_status(session_obj, SessionStatus.TRANSCRIBED)
    await db_session.commit()
    return subject.id, session_obj.id


async def _insert_utterances(
    db_session: AsyncSession,
    subject_id: uuid.UUID,
    session_id: uuid.UUID,
    count: int,
    duration_ms: int = 2000,
) -> None:
    repo = UtteranceRepository(db_session)
    rows = [
        {
            "session_id": session_id,
            "seq": i,
            "start_ms": i * duration_ms,
            "end_ms": (i + 1) * duration_ms,
            "text": f"utterance {i}",
            "asr_confidence": 0.9,
            "words": [],
            "speaker_tag": None,
            "embed_model_ver": "qwen3-0.6b-v1",
        }
        for i in range(count)
    ]
    await repo.bulk_insert(subject_id, rows)
    await db_session.commit()


class TestSpeakerTagsAssigned:
    """T20.1 - speaker tags assigned; multiple speakers detected.

    NOTE: this exercises the assignment MECHANISM with a synthetic backend
    standing in for pyannote.audio's segment output - see module docstring.
    """

    async def test_speaker_tags_assigned_from_synthetic_segments(
        self, db_session: AsyncSession, session_factory: Any
    ) -> None:
        subject_id, session_id = await _create_subject_and_session(db_session)
        await _insert_utterances(db_session, subject_id, session_id, count=6)

        # 3 distinct synthetic speakers, one per pair of utterances (each
        # utterance is [i*2000, (i+1)*2000)).
        segments = [
            _Segment(0, 4000, speaker_index=0),
            _Segment(4000, 8000, speaker_index=1),
            _Segment(8000, 12000, speaker_index=2),
        ]
        backend = FakeDiarisationBackend(segments)
        worker = DiarisationWorker(session_factory, backend=backend)

        tag_map = await worker.assign_speaker_tags(session_id, audio_path="fake://audio.wav")

        distinct_tags = set(tag_map.values())
        assert distinct_tags == {
            SpeakerTag.SPK_A.value,
            SpeakerTag.SPK_B.value,
            SpeakerTag.SPK_C.value,
        }
        assert len(distinct_tags) >= 3
        assert backend.calls == [("fake://audio.wav", 5)]

    async def test_single_speaker_session_all_spk_a(
        self, db_session: AsyncSession, session_factory: Any
    ) -> None:
        """Edge case: single speaker session -> all utterances tagged SPK_A."""
        subject_id, session_id = await _create_subject_and_session(db_session)
        await _insert_utterances(db_session, subject_id, session_id, count=4)

        worker = DiarisationWorker(session_factory, backend=None)
        result = await worker.process_session(session_id, enable_diarisation=True)

        assert result.state == DiarisationState.TAGGED
        assert set(result.utterance_speaker_map.values()) == {SpeakerTag.SPK_A.value}

    async def test_more_than_five_speakers_capped_rest_unknown(
        self, db_session: AsyncSession, session_factory: Any
    ) -> None:
        """Edge case: many speakers (>5) -> cap at SPK_A-SPK_E; rest UNKNOWN."""
        subject_id, session_id = await _create_subject_and_session(db_session)
        await _insert_utterances(db_session, subject_id, session_id, count=7)

        segments = [_Segment(i * 2000, (i + 1) * 2000, speaker_index=i) for i in range(7)]
        backend = FakeDiarisationBackend(segments)
        worker = DiarisationWorker(session_factory, backend=backend)

        tag_map = await worker.assign_speaker_tags(session_id, audio_path="fake://audio.wav")

        assert len(tag_map) == 7
        assigned = list(tag_map.values())
        assert assigned[:MAX_ASSIGNABLE_SPEAKERS] == [
            SpeakerTag.SPK_A.value,
            SpeakerTag.SPK_B.value,
            SpeakerTag.SPK_C.value,
            SpeakerTag.SPK_D.value,
            SpeakerTag.SPK_E.value,
        ]
        assert assigned[5] == SpeakerTag.UNKNOWN.value
        assert assigned[6] == SpeakerTag.UNKNOWN.value

    @pytest.mark.skip(
        reason=(
            "Blocked: pyannote.audio is not installed (deliberately, see module "
            "docstring) and its pretrained model is HuggingFace-gated with no "
            "HF_TOKEN configured in .env here. There is no working GPU on this "
            "host either (nvidia-smi: driver/library version mismatch). Cannot "
            "honestly run real multi-speaker diarisation on real audio - the "
            "tag-assignment mechanism is instead verified with a synthetic "
            "backend in test_speaker_tags_assigned_from_synthetic_segments."
        )
    )
    def test_real_pyannote_three_plus_speakers_detected(self) -> None:
        raise NotImplementedError


class TestNoBiometricData:
    """T20.2 - NFR-S4: no voiceprint/embedding/biometric template persisted anywhere."""

    async def test_no_biometric_data(self, db_session: AsyncSession) -> None:
        audit = NFRS4Audit(db_session, storage=None)
        schema_violations = await audit.audit_database_schema()
        assert schema_violations == [], f"Biometric columns found: {schema_violations}"

    async def test_audit_session_compliant(self, db_session: AsyncSession) -> None:
        subject_id, session_id = await _create_subject_and_session(db_session)
        await _insert_utterances(db_session, subject_id, session_id, count=2)

        audit = NFRS4Audit(db_session, storage=None)
        result = await audit.audit_session(session_id)

        assert result.compliant is True
        assert result.voiceprints_found == 0
        assert result.embeddings_persisted == 0
        assert result.biometric_templates == 0
        assert result.speaker_tags_session_scoped is True
        assert result.cross_session_linkage_possible is False

    async def test_schema_audit_detects_planted_biometric_column(
        self, db_session: AsyncSession
    ) -> None:
        """Sanity check: the audit actually detects a violation if one exists,
        rather than trivially passing regardless of schema contents."""
        await db_session.execute(
            text("CREATE TABLE IF NOT EXISTS _s20_test_biometric (voiceprint_hash text)")
        )
        try:
            audit = NFRS4Audit(db_session, storage=None)
            violations = await audit.audit_database_schema()
            assert any("voiceprint_hash" in v for v in violations)
        finally:
            await db_session.execute(text("DROP TABLE IF EXISTS _s20_test_biometric"))


class TestTagsNotLinkable:
    """T20.3 - speaker tags from two sessions are not linkable across sessions.

    Tags are session-local strings (e.g. "SPK_A"); the SAME literal string
    appearing in both sessions is EXPECTED, not a violation. Linkability
    means a resolvable identifier/join path ties one session's tag to the
    same real person in another session - which this schema has no mechanism
    for (see NFRS4Audit._cross_session_tag_linkage).
    """

    async def test_tags_not_linkable(self, db_session: AsyncSession, session_factory: Any) -> None:
        subject_a, session_a = await _create_subject_and_session(db_session)
        subject_b, session_b = await _create_subject_and_session(db_session)
        await _insert_utterances(db_session, subject_a, session_a, count=2)
        await _insert_utterances(db_session, subject_b, session_b, count=2)

        worker = DiarisationWorker(session_factory, backend=None)
        await worker.process_session(session_a, enable_diarisation=True)
        await worker.process_session(session_b, enable_diarisation=True)

        audit = NFRS4Audit(db_session, storage=None)
        assertion = await audit.verify_non_linkability(session_a, session_b)

        # Both sessions have single-speaker SPK_A tags -> literal string
        # overlap IS expected and must not be treated as a violation.
        assert assertion.tags_session_a == ["SPK_A"]
        assert assertion.tags_session_b == ["SPK_A"]
        assert assertion.overlap_count == 1
        assert assertion.linkable is False
        assert assertion.assertion_passed is True

    async def test_no_cross_session_linking_table_exists(self, db_session: AsyncSession) -> None:
        audit = NFRS4Audit(db_session, storage=None)
        linking_tables = await audit._cross_session_tag_linkage()
        assert linking_tables == []


class TestDiarisationDisabled:
    """T20.4 - pipeline completes with diarisation disabled; tags stay NULL."""

    async def test_diarisation_disabled(
        self, db_session: AsyncSession, session_factory: Any
    ) -> None:
        subject_id, session_id = await _create_subject_and_session(db_session)
        await _insert_utterances(db_session, subject_id, session_id, count=3)

        worker = DiarisationWorker(session_factory, backend=None)
        result = await worker.process_session(session_id, enable_diarisation=False)

        assert result.state == DiarisationState.DISABLED
        assert result.speaker_count == 0
        assert result.utterance_speaker_map == {}

        repo = UtteranceRepository(db_session)
        db_session.expire_all()
        persisted = await repo.get_by_session(subject_id, session_id)
        assert len(persisted) == 3
        assert all(u.speaker_tag is None for u in persisted)

    async def test_diarisation_disabled_via_settings(
        self, db_session: AsyncSession, session_factory: Any
    ) -> None:
        """DIARISATION_ENABLED=false in settings also disables it even if the
        caller passes enable_diarisation=True."""
        subject_id, session_id = await _create_subject_and_session(db_session)
        await _insert_utterances(db_session, subject_id, session_id, count=2)

        settings = Settings(DIARISATION_ENABLED=False)
        worker = DiarisationWorker(session_factory, settings=settings, backend=None)
        result = await worker.process_session(session_id, enable_diarisation=True)

        assert result.state == DiarisationState.DISABLED
        repo = UtteranceRepository(db_session)
        db_session.expire_all()
        persisted = await repo.get_by_session(subject_id, session_id)
        assert all(u.speaker_tag is None for u in persisted)
