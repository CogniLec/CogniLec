"""Wiring: consume processed chunks, compute/aggregate quality, publish warnings (S18).

Integration point: this module is called per-chunk with the S17
`ProcessedChunk` output (already resampled/denoised/VAD-processed) plus the
raw sample array used to derive it. It does not re-implement VAD or
preprocessing - it only measures quality metrics and reacts to them.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from src.core.config import Settings, get_settings
from src.db.repositories.session_repo import SessionRepository
from src.services.audio_quality.evaluator import QualityEvaluator
from src.services.audio_quality.metrics import (
    FloatArray,
    compute_clipping_rate,
    compute_lufs_estimate,
    compute_rms_db,
    compute_snr_db,
)
from src.services.audio_quality.models import ChunkQualityMetrics, QualityWarning
from src.services.valkey_stream import ValkeyStreamProducer

logger = logging.getLogger(__name__)

AUDIO_QUALITY_STREAM = "audio.quality"


def compute_chunk_metrics(
    session_id: UUID,
    sequence: int,
    samples: FloatArray,
    speech_ratio: float,
) -> ChunkQualityMetrics:
    """Compute per-chunk quality metrics from a float32 PCM sample array.

    `speech_ratio` is taken as-is from S17's VAD output rather than
    recomputed here - S18 only measures signal quality, not speech presence.
    """
    try:
        snr_db = compute_snr_db(samples)
        clipping_rate = compute_clipping_rate(samples)
        rms_db = compute_rms_db(samples)
        lufs = compute_lufs_estimate(samples)
    except Exception:
        logger.exception(
            "quality.compute_chunk_metrics failed session=%s sequence=%s", session_id, sequence
        )
        raise
    return ChunkQualityMetrics(
        session_id=session_id,
        sequence=sequence,
        snr_db=snr_db,
        speech_ratio=speech_ratio,
        clipping_rate=clipping_rate,
        lufs=lufs,
        rms_db=rms_db,
        computed_at=datetime.now(UTC),
    )


def quality_metrics_to_stream_fields(metrics: ChunkQualityMetrics) -> dict[str, str]:
    """Serialize metrics to the `audio.quality` stream field contract."""
    fields: dict[str, str] = {
        "session_id": str(metrics.session_id),
        "sequence": str(metrics.sequence),
        "snr_db": str(metrics.snr_db),
        "speech_ratio": str(metrics.speech_ratio),
        "clipping_rate": str(metrics.clipping_rate),
    }
    if metrics.lufs is not None:
        fields["lufs"] = str(metrics.lufs)
    return fields


def warning_to_sse_payload(warning: QualityWarning) -> dict[str, object]:
    """Serialize a QualityWarning to the `audio_warning` SSE event data contract."""
    return {
        "session_id": str(warning.session_id),
        "warning_type": warning.warning_type,
        "severity": warning.severity,
        "message": warning.message,
        "metric_value": warning.metric_value,
        "threshold": warning.threshold,
        "timestamp": warning.timestamp.isoformat(),
    }


class AudioQualityService:
    """Coordinates metric computation, aggregation, persistence, and SSE warnings."""

    def __init__(
        self,
        evaluator: QualityEvaluator | None = None,
        stream: ValkeyStreamProducer | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._evaluator = evaluator or QualityEvaluator(self._settings)
        self._stream = stream

    async def process_chunk(
        self,
        session_id: UUID,
        sequence: int,
        samples: FloatArray,
        speech_ratio: float,
        session_repo: SessionRepository | None = None,
    ) -> tuple[ChunkQualityMetrics, list[QualityWarning]]:
        """Compute metrics for one chunk, aggregate, persist score, emit warnings."""
        try:
            metrics = compute_chunk_metrics(session_id, sequence, samples, speech_ratio)
        except Exception:
            # Edge case: metric computation fails -> skip chunk, keep going.
            return (
                ChunkQualityMetrics(
                    session_id=session_id,
                    sequence=sequence,
                    snr_db=0.0,
                    speech_ratio=speech_ratio,
                    clipping_rate=0.0,
                    lufs=None,
                    rms_db=None,
                    computed_at=datetime.now(UTC),
                ),
                [],
            )

        score, warnings = self._evaluator.process_chunk(metrics)

        if self._stream is not None:
            await self._stream.xadd_quality(quality_metrics_to_stream_fields(metrics))

        if session_repo is not None:
            session_obj = await session_repo.get(session_id)
            if session_obj is not None:
                await session_repo.update_audio_quality(session_obj, score.overall_score)

        if self._stream is not None and self._settings.QUALITY_WARNINGS_ENABLED:
            for warning in warnings:
                logger.warning(
                    "quality.evaluate_threshold breach session=%s type=%s severity=%s",
                    session_id,
                    warning.warning_type,
                    warning.severity,
                )
                await self._stream.publish_event(
                    str(session_id), "audio_warning", warning_to_sse_payload(warning)
                )

        return metrics, warnings
