"""HallucinationWorker - runs HallucinationDetector over a session's utterances
and persists soft-delete flags (S22).

Runs after DualASRWorker (S21). Never raises: a detector failure is caught
inside HallucinationDetector.detect() itself, and this worker never removes
rows - only sets `is_relevant=false, filter_reason=...` (FR-2.15).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from src.core.config import Settings, get_settings
from src.db.repositories.session_repo import SessionRepository
from src.db.repositories.utterance_repo import UtteranceRepository
from src.ml.hallucination import HallucinationConfig, HallucinationDetector, VADRegion

logger = logging.getLogger(__name__)


@dataclass
class HallucinationRunResult:
    session_id: UUID
    utterances_total: int
    flagged_count: int


class HallucinationWorker:
    def __init__(
        self,
        session_factory: object,
        settings: Settings | None = None,
        detector: HallucinationDetector | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._session_factory = session_factory
        self._detector = detector or HallucinationDetector(
            HallucinationConfig(
                agreement_threshold=self._settings.HALLUCINATION_AGREEMENT_THRESHOLD,
                max_repeat_ngram=self._settings.HALLUCINATION_MAX_REPEAT_NGRAM,
                max_repeat_count=self._settings.HALLUCINATION_MAX_REPEAT_COUNT,
                vad_margin_ms=self._settings.HALLUCINATION_VAD_MARGIN_MS,
                min_utterance_length_ms=self._settings.HALLUCINATION_MIN_UTTERANCE_LENGTH_MS,
            )
        )

    async def process_session(
        self,
        session_id: UUID,
        vad_regions: list[VADRegion] | None = None,
    ) -> HallucinationRunResult:
        if not self._settings.HALLUCINATION_DETECTION_ENABLED:
            return HallucinationRunResult(
                session_id=session_id, utterances_total=0, flagged_count=0
            )

        async with self._session_factory() as db_session:  # type: ignore[operator]
            session_repo = SessionRepository(db_session)
            session_obj = await session_repo.get_or_raise(session_id)
            subject_id = session_obj.subject_id

            utterance_repo = UtteranceRepository(db_session)
            utterances = await utterance_repo.get_by_session(subject_id, session_id)
            if not utterances:
                return HallucinationRunResult(
                    session_id=session_id, utterances_total=0, flagged_count=0
                )

            flags: dict[int, tuple[bool, str | None, float | None]] = {}
            flagged_count = 0
            for utt in utterances:
                result = self._detector.detect(utt, vad_regions)
                if result.is_hallucination:
                    flagged_count += 1
                    flags[utt.seq] = (False, result.filter_reason, result.confidence)

            if flags:
                await utterance_repo.apply_relevance_flags(subject_id, session_id, flags)
                await db_session.commit()

            logger.info(
                "hallucination.detect_session session_id=%s flagged=%d total=%d",
                session_id,
                flagged_count,
                len(utterances),
            )
            return HallucinationRunResult(
                session_id=session_id, utterances_total=len(utterances), flagged_count=flagged_count
            )
