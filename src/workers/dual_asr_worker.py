"""DualASRWorker - secondary ASR model + agreement scoring (S21).

Real secondary ASR (faster-whisper/NeMo canary/parakeet, per the S21 spec)
runs through a pluggable `SecondaryASRBackend`. In this environment no such
model is installed or downloadable (see tests/test_dual_asr_worker.py's
module docstring for the same honesty caveat already established by
tests/test_diarisation.py). This worker's mechanism - alignment by timestamp
IoU, token-F1 agreement scoring, graceful degradation when the backend is
absent or raises - is fully exercised with a synthetic backend.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from src.core.config import Settings, get_settings
from src.db.repositories.session_repo import SessionRepository
from src.db.repositories.utterance_repo import UtteranceRepository

logger = logging.getLogger(__name__)


@dataclass
class SecondaryUtterance:
    text: str
    start_ms: int
    end_ms: int
    confidence: float = 0.0


@dataclass
class AlignmentPair:
    primary_seq: int
    secondary_text: str | None
    iou: float
    agreement: float | None


@dataclass
class DualASRResult:
    session_id: UUID
    utterances_total: int
    utterances_aligned: int
    mean_agreement: float | None
    min_agreement: float | None
    duration_ms: int
    degraded: bool = False


class PrimaryUtteranceLike(Protocol):
    seq: int
    start_ms: int
    end_ms: int
    text: str


class SecondaryASRBackend(Protocol):
    """Pluggable secondary ASR backend. Real implementation wraps
    faster-whisper/NeMo; tests inject a synthetic one."""

    def transcribe(self, audio_path: str) -> list[SecondaryUtterance]: ...


def _normalize_tokens(text: str) -> list[str]:
    cleaned = re.sub(r"[^\w\s]", "", text.lower())
    return cleaned.split()


def compute_agreement(primary_text: str, secondary_text: str) -> float:
    """Token-level F1 agreement score in [0.0, 1.0]."""
    p_tokens = _normalize_tokens(primary_text)
    s_tokens = _normalize_tokens(secondary_text)
    if not p_tokens and not s_tokens:
        return 1.0
    if not p_tokens or not s_tokens:
        return 0.0

    p_counts: dict[str, int] = {}
    for tok in p_tokens:
        p_counts[tok] = p_counts.get(tok, 0) + 1
    s_counts: dict[str, int] = {}
    for tok in s_tokens:
        s_counts[tok] = s_counts.get(tok, 0) + 1

    intersection = sum(min(p_counts.get(tok, 0), cnt) for tok, cnt in s_counts.items())
    precision = intersection / len(s_tokens)
    recall = intersection / len(p_tokens)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def _iou(a_start: int, a_end: int, b_start: int, b_end: int) -> float:
    overlap = max(0, min(a_end, b_end) - max(a_start, b_start))
    union = (a_end - a_start) + (b_end - b_start) - overlap
    if union <= 0:
        return 0.0
    return overlap / union


class DualASRWorker:
    """Runs the secondary ASR model on a session and computes agreement."""

    def __init__(
        self,
        session_factory: object,
        settings: Settings | None = None,
        backend: SecondaryASRBackend | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._session_factory = session_factory
        self._backend = backend

    def align_utterances(
        self,
        primary: Sequence[PrimaryUtteranceLike],
        secondary: Sequence[SecondaryUtterance],
        iou_threshold: float = 0.3,
    ) -> list[AlignmentPair]:
        """Align primary and secondary utterances by timestamp IoU."""
        pairs: list[AlignmentPair] = []
        for p in primary:
            best_iou = 0.0
            best_secondary: SecondaryUtterance | None = None
            for s in secondary:
                iou = _iou(p.start_ms, p.end_ms, s.start_ms, s.end_ms)
                if iou > best_iou:
                    best_iou = iou
                    best_secondary = s

            if best_secondary is not None and best_iou >= iou_threshold:
                pairs.append(
                    AlignmentPair(
                        primary_seq=p.seq,
                        secondary_text=best_secondary.text,
                        iou=best_iou,
                        agreement=compute_agreement(p.text, best_secondary.text),
                    )
                )
            else:
                pairs.append(
                    AlignmentPair(primary_seq=p.seq, secondary_text=None, iou=0.0, agreement=None)
                )
        return pairs

    async def process_session(
        self,
        session_id: UUID,
        audio_path: str | None = None,
    ) -> DualASRResult:
        """Run secondary ASR, align to primary utterances, persist agreement.

        Degrades gracefully: any backend failure (missing model, load error,
        timeout) leaves `asr_agreement = NULL` for all utterances and never
        raises or blocks the pipeline (T21.3).
        """
        start = time.monotonic()

        async with self._session_factory() as db_session:  # type: ignore[operator]
            session_repo = SessionRepository(db_session)
            session_obj = await session_repo.get_or_raise(session_id)
            subject_id = session_obj.subject_id

            utterance_repo = UtteranceRepository(db_session)
            primary = await utterance_repo.get_by_session(subject_id, session_id)

            if not primary:
                return DualASRResult(
                    session_id=session_id,
                    utterances_total=0,
                    utterances_aligned=0,
                    mean_agreement=None,
                    min_agreement=None,
                    duration_ms=int((time.monotonic() - start) * 1000),
                )

            if not self._settings.DUAL_ASR_ENABLED or self._backend is None or audio_path is None:
                return DualASRResult(
                    session_id=session_id,
                    utterances_total=len(primary),
                    utterances_aligned=0,
                    mean_agreement=None,
                    min_agreement=None,
                    duration_ms=int((time.monotonic() - start) * 1000),
                    degraded=True,
                )

            try:
                secondary = self._backend.transcribe(audio_path)
                pairs = self.align_utterances(primary, secondary)
            except Exception:
                logger.exception(
                    "secondary ASR failed; utterances retain asr_agreement=NULL",
                    extra={"session_id": str(session_id)},
                )
                return DualASRResult(
                    session_id=session_id,
                    utterances_total=len(primary),
                    utterances_aligned=0,
                    mean_agreement=None,
                    min_agreement=None,
                    duration_ms=int((time.monotonic() - start) * 1000),
                    degraded=True,
                )

            scores: dict[int, float | None] = {pair.primary_seq: pair.agreement for pair in pairs}
            await utterance_repo.apply_agreement_scores(subject_id, session_id, scores)
            await db_session.commit()

            aligned_agreements = [p.agreement for p in pairs if p.agreement is not None]
            mean_agreement = (
                sum(aligned_agreements) / len(aligned_agreements) if aligned_agreements else None
            )
            min_agreement = min(aligned_agreements) if aligned_agreements else None

            return DualASRResult(
                session_id=session_id,
                utterances_total=len(primary),
                utterances_aligned=len(aligned_agreements),
                mean_agreement=mean_agreement,
                min_agreement=min_agreement,
                duration_ms=int((time.monotonic() - start) * 1000),
            )
