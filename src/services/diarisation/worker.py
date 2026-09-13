"""DiarisationWorker - anonymous speaker diarisation over a session's utterances (S20).

Real multi-speaker diarisation uses pyannote.audio (3.x) as a pluggable
`DiarisationBackend`. In THIS environment pyannote.audio is not installed and
could not be exercised even if it were: its pretrained pipelines are gated on
HuggingFace and require an access token + license acceptance, and no
`HF_TOKEN`/`HUGGINGFACE_TOKEN` is configured in `.env` here (only `HF_HOME`,
a cache directory, is set). See tests/test_diarisation.py's module docstring
for the full honesty statement - this worker's mechanism (segment ->
utterance mapping, tag capping, persistence, disabled-mode fallback) is
exercised with a synthetic `DiarisationBackend`, not real pyannote.
"""

from __future__ import annotations

import logging
import time
from typing import Protocol
from uuid import UUID

from src.core.config import Settings, get_settings
from src.db.repositories.session_repo import SessionRepository
from src.db.repositories.utterance_repo import UtteranceRepository
from src.services.diarisation.models import DiarisationResult, DiarisationState, SpeakerTag

logger = logging.getLogger(__name__)

# SpeakerTag members excluding UNKNOWN, in assignment order (SPK_A first).
_ASSIGNABLE_TAGS: list[str] = [t.value for t in SpeakerTag if t is not SpeakerTag.UNKNOWN]
MAX_ASSIGNABLE_SPEAKERS = len(_ASSIGNABLE_TAGS)  # 5: SPK_A..SPK_E


class DiarisationSegment(Protocol):
    """One diarised segment: a time span attributed to one local speaker index."""

    start_ms: int
    end_ms: int
    speaker_index: int


class DiarisationBackend(Protocol):
    """Pluggable diarisation backend. The real implementation wraps
    pyannote.audio; tests inject a synthetic one (see FakeDiarisationBackend
    in tests/test_diarisation.py)."""

    def diarise(self, audio_path: str, max_speakers: int) -> list[DiarisationSegment]:
        """Return diarised segments for the audio at `audio_path`."""
        ...


def _speaker_index_to_tag(index: int) -> str:
    """Map a 0-based local speaker index to a capped SPK_A..SPK_E tag,
    per the edge case: >5 speakers -> the remainder tagged UNKNOWN."""
    if 0 <= index < MAX_ASSIGNABLE_SPEAKERS:
        return _ASSIGNABLE_TAGS[index]
    return SpeakerTag.UNKNOWN.value


def _midpoint_ms(start_ms: int, end_ms: int) -> int:
    return (start_ms + end_ms) // 2


class DiarisationWorker:
    """Applies anonymous, session-scoped speaker tags to a session's utterances."""

    def __init__(
        self,
        session_factory: object,
        settings: Settings | None = None,
        backend: DiarisationBackend | None = None,
    ) -> None:
        """`session_factory` is a zero-arg callable returning a new AsyncSession
        (matches ASRWorker's convention), so each call gets its own DB
        session/transaction."""
        self._settings = settings or get_settings()
        self._session_factory = session_factory
        self._backend = backend

    async def process_session(
        self,
        session_id: UUID,
        enable_diarisation: bool = True,
        audio_path: str | None = None,
    ) -> DiarisationResult:
        """Apply diarisation to all utterances in a session.

        Tags are session-scoped only. Never persisted as biometric data -
        only the anonymous tag string (e.g. "SPK_A") is ever written.

        `audio_path` is optional and additional to the spec's interface: when
        a `DiarisationBackend` is configured and `audio_path` is supplied,
        the backend is run over that audio and its segments drive the tag
        assignment; otherwise (no backend, or no audio_path) a single-speaker
        fallback (all utterances -> SPK_A) is used, per the edge-case matrix.
        """
        start = time.monotonic()
        effective_enabled = enable_diarisation and self._settings.DIARISATION_ENABLED

        async with self._session_factory() as db_session:  # type: ignore[operator]
            session_repo = SessionRepository(db_session)
            session_obj = await session_repo.get_or_raise(session_id)
            subject_id = session_obj.subject_id

            if not effective_enabled:
                logger.info(
                    "diarisation disabled; utterances left untagged",
                    extra={"session_id": str(session_id)},
                )
                return DiarisationResult(
                    session_id=session_id,
                    speaker_count=0,
                    utterance_speaker_map={},
                    processing_time_ms=int((time.monotonic() - start) * 1000),
                    model_name=self._settings.DIARISATION_MODEL,
                    state=DiarisationState.DISABLED,
                )

            utterance_repo = UtteranceRepository(db_session)
            utterances = await utterance_repo.get_by_session(subject_id, session_id)
            if not utterances:
                logger.info(
                    "session has no utterances; diarisation produces no tags",
                    extra={"session_id": str(session_id)},
                )
                return DiarisationResult(
                    session_id=session_id,
                    speaker_count=0,
                    utterance_speaker_map={},
                    processing_time_ms=int((time.monotonic() - start) * 1000),
                    model_name=self._settings.DIARISATION_MODEL,
                    state=DiarisationState.COMPLETE,
                )

            try:
                segments = None
                if self._backend is not None and audio_path is not None:
                    segments = self._backend.diarise(
                        audio_path, self._settings.DIARISATION_MAX_SPEAKERS
                    )
                tag_map = self._assign_tags_from_segments(
                    utterances=[(u.seq, u.start_ms, u.end_ms) for u in utterances],
                    segments=segments,
                    require_backend=False,
                )
            except Exception:
                logger.exception(
                    "diarisation failed; utterances retain no speaker tag",
                    extra={"session_id": str(session_id)},
                )
                return DiarisationResult(
                    session_id=session_id,
                    speaker_count=0,
                    utterance_speaker_map={},
                    processing_time_ms=int((time.monotonic() - start) * 1000),
                    model_name=self._settings.DIARISATION_MODEL,
                    state=DiarisationState.FAILED,
                )

            await utterance_repo.update_speaker_tags(subject_id, session_id, tag_map)
            await db_session.commit()

            distinct_tags = {t for t in tag_map.values() if t != SpeakerTag.UNKNOWN.value}
            logger.info(
                "diarisation complete",
                extra={"session_id": str(session_id), "speaker_count": len(distinct_tags)},
            )
            return DiarisationResult(
                session_id=session_id,
                speaker_count=len(distinct_tags),
                utterance_speaker_map=tag_map,
                processing_time_ms=int((time.monotonic() - start) * 1000),
                model_name=self._settings.DIARISATION_MODEL,
                state=DiarisationState.TAGGED,
            )

    async def assign_speaker_tags(
        self,
        session_id: UUID,
        audio_path: str,
    ) -> dict[int, str]:
        """Assign anonymous speaker tags to utterances based on audio.

        Runs the configured `DiarisationBackend` (real pyannote.audio, or a
        test double) over `audio_path` and maps each utterance's midpoint
        timestamp to the overlapping diarised segment's speaker.
        """
        async with self._session_factory() as db_session:  # type: ignore[operator]
            session_repo = SessionRepository(db_session)
            session_obj = await session_repo.get_or_raise(session_id)
            utterance_repo = UtteranceRepository(db_session)
            utterances = await utterance_repo.get_by_session(session_obj.subject_id, session_id)

        if self._backend is None:
            logger.warning(
                "no diarisation backend configured; all tags UNKNOWN",
                extra={"session_id": str(session_id)},
            )
            return {u.seq: SpeakerTag.UNKNOWN.value for u in utterances}

        segments = self._backend.diarise(audio_path, self._settings.DIARISATION_MAX_SPEAKERS)
        return self._assign_tags_from_segments(
            utterances=[(u.seq, u.start_ms, u.end_ms) for u in utterances],
            segments=segments,
            require_backend=True,
        )

    def _assign_tags_from_segments(
        self,
        utterances: list[tuple[int, int, int]],
        segments: list[DiarisationSegment] | None = None,
        require_backend: bool = False,
    ) -> dict[int, str]:
        """Map (seq, start_ms, end_ms) utterances to speaker tags.

        If no segments are available, falls back to a single-speaker
        assumption (SPK_A) per the edge case matrix ("single speaker session
        -> all utterances tagged SPK_A") - the best-effort default when no
        real diarisation backend/audio is wired up. `require_backend=True`
        (used by `assign_speaker_tags`, which always has a backend) instead
        tags everything UNKNOWN if segments end up empty.
        """
        if segments is None:
            if require_backend:
                return {seq: SpeakerTag.UNKNOWN.value for seq, _start, _end in utterances}
            return {seq: SpeakerTag.SPK_A.value for seq, _start, _end in utterances}

        tag_map: dict[int, str] = {}
        for seq, start_ms, end_ms in utterances:
            mid = _midpoint_ms(start_ms, end_ms)
            match = next(
                (s for s in segments if s.start_ms <= mid < s.end_ms),
                None,
            )
            tag_map[seq] = (
                _speaker_index_to_tag(match.speaker_index) if match else SpeakerTag.UNKNOWN.value
            )
        return tag_map
