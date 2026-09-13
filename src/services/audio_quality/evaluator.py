"""Rolling-window quality aggregation & threshold evaluation (S18)."""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
from uuid import UUID

import numpy as np
from src.core.config import Settings, get_settings
from src.services.audio_quality.models import (
    ChunkQualityMetrics,
    QualityWarning,
    SessionQualityScore,
)

# Severity ranking, worst last, used to pick the overall session status.
_SEVERITY_ORDER = {"normal": 0, "degraded": 1, "warning": 2, "critical": 3}


def _weighted_average(values: list[float]) -> float:
    """Weight recent (later) values more heavily via a linear ramp."""
    if not values:
        return 0.0
    weights = np.arange(1, len(values) + 1, dtype=np.float64)
    return float(np.average(np.array(values, dtype=np.float64), weights=weights))


class _SessionWindow:
    """Rolling window + cooldown bookkeeping for a single session."""

    def __init__(self, window_size: int) -> None:
        self.chunks: deque[ChunkQualityMetrics] = deque(maxlen=window_size)
        self.last_warning_at: dict[str, datetime] = {}


class QualityEvaluator:
    """Aggregates per-chunk metrics into a session score and raises warnings.

    One instance is expected to live for the lifetime of a worker process,
    holding per-session rolling windows in memory (the DB only ever gets the
    final aggregated score via SessionRepository.update_audio_quality).
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._windows: dict[UUID, _SessionWindow] = {}

    def _window_for(self, session_id: UUID) -> _SessionWindow:
        window = self._windows.get(session_id)
        if window is None:
            window = _SessionWindow(self._settings.QUALITY_ROLLING_WINDOW_SIZE)
            self._windows[session_id] = window
        return window

    def reset_session(self, session_id: UUID) -> None:
        self._windows.pop(session_id, None)

    def process_chunk(
        self, metrics: ChunkQualityMetrics
    ) -> tuple[SessionQualityScore, list[QualityWarning]]:
        """Feed one chunk's metrics in; returns the updated score and any warnings."""
        window = self._window_for(metrics.session_id)
        window.chunks.append(metrics)

        score = self._aggregate(metrics.session_id, window)
        warnings: list[QualityWarning] = []
        if len(window.chunks) >= self._settings.QUALITY_MIN_CHUNKS:
            warnings = self._check_thresholds(metrics.session_id, window, score)
        return score, warnings

    def _aggregate(self, session_id: UUID, window: _SessionWindow) -> SessionQualityScore:
        chunks = list(window.chunks)
        snr_values = [c.snr_db for c in chunks]
        speech_values = [c.speech_ratio for c in chunks]
        clip_values = [c.clipping_rate for c in chunks]

        avg_snr = _weighted_average(snr_values)
        avg_speech = _weighted_average(speech_values)
        avg_clip = _weighted_average(clip_values)
        window_snr = _weighted_average(snr_values)

        status = self._status_for(avg_snr, avg_clip)
        overall_score = self._overall_score(avg_snr, avg_clip)

        return SessionQualityScore(
            session_id=session_id,
            avg_snr_db=avg_snr,
            avg_speech_ratio=avg_speech,
            avg_clipping_rate=avg_clip,
            overall_score=overall_score,
            chunk_count=len(chunks),
            window_snr_db=window_snr,
            status=status,
            last_updated=datetime.now(UTC),
        )

    def _status_for(self, avg_snr: float, avg_clip: float) -> str:
        s = self._settings
        snr_status = "normal"
        if avg_snr < s.QUALITY_SNR_CRITICAL_DB:
            snr_status = "critical"
        elif avg_snr < s.QUALITY_SNR_WARNING_DB:
            snr_status = "warning"
        elif avg_snr < s.QUALITY_SNR_DEGRADED_DB:
            snr_status = "degraded"

        clip_status = "normal"
        if avg_clip > s.QUALITY_CLIPPING_CRITICAL:
            clip_status = "critical"
        elif avg_clip > s.QUALITY_CLIPPING_WARNING:
            clip_status = "warning"

        worst = max((snr_status, clip_status), key=lambda st: _SEVERITY_ORDER[st])
        return worst

    def _overall_score(self, avg_snr: float, avg_clip: float) -> float:
        # Normalize SNR onto [0,1] between critical and a comfortable ceiling.
        s = self._settings
        ceiling_db = s.QUALITY_SNR_DEGRADED_DB + 10.0
        span = ceiling_db - s.QUALITY_SNR_CRITICAL_DB
        snr_component = (avg_snr - s.QUALITY_SNR_CRITICAL_DB) / span if span > 0 else 1.0
        snr_component = min(max(snr_component, 0.0), 1.0)
        clip_component = 1.0 - min(avg_clip / max(s.QUALITY_CLIPPING_CRITICAL * 2, 1e-6), 1.0)
        return float(round(0.7 * snr_component + 0.3 * clip_component, 4))

    def _check_thresholds(
        self,
        session_id: UUID,
        window: _SessionWindow,
        score: SessionQualityScore,
    ) -> list[QualityWarning]:
        s = self._settings
        now = datetime.now(UTC)
        warnings: list[QualityWarning] = []

        def _emit(
            warning_type: str, severity: str, message: str, value: float, threshold: float
        ) -> None:
            last = window.last_warning_at.get(warning_type)
            if last is not None and (now - last).total_seconds() < s.QUALITY_WARNING_COOLDOWN_S:
                return
            window.last_warning_at[warning_type] = now
            warnings.append(
                QualityWarning(
                    session_id=session_id,
                    warning_type=warning_type,
                    severity=severity,
                    message=message,
                    metric_value=value,
                    threshold=threshold,
                    timestamp=now,
                )
            )

        if score.avg_snr_db < s.QUALITY_SNR_CRITICAL_DB:
            _emit(
                "low_snr",
                "critical",
                f"Audio SNR critically low ({score.avg_snr_db:.1f} dB < "
                f"{s.QUALITY_SNR_CRITICAL_DB:.1f} dB). Check microphone placement.",
                score.avg_snr_db,
                s.QUALITY_SNR_CRITICAL_DB,
            )
        elif score.avg_snr_db < s.QUALITY_SNR_WARNING_DB:
            _emit(
                "low_snr",
                "warning",
                f"Audio SNR below threshold ({score.avg_snr_db:.1f} dB < "
                f"{s.QUALITY_SNR_WARNING_DB:.1f} dB). Consider repositioning the device.",
                score.avg_snr_db,
                s.QUALITY_SNR_WARNING_DB,
            )
        elif score.avg_snr_db < s.QUALITY_SNR_DEGRADED_DB:
            _emit(
                "low_snr",
                "degraded",
                f"Audio SNR degraded ({score.avg_snr_db:.1f} dB < "
                f"{s.QUALITY_SNR_DEGRADED_DB:.1f} dB).",
                score.avg_snr_db,
                s.QUALITY_SNR_DEGRADED_DB,
            )

        # speech_ratio=0 is expected silence between chunks, never a warning.
        if 0.0 < score.avg_speech_ratio < s.QUALITY_SPEECH_RATIO_MIN:
            _emit(
                "low_speech_ratio",
                "warning",
                f"Speech ratio low ({score.avg_speech_ratio:.2f} < "
                f"{s.QUALITY_SPEECH_RATIO_MIN:.2f}).",
                score.avg_speech_ratio,
                s.QUALITY_SPEECH_RATIO_MIN,
            )

        if score.avg_clipping_rate > s.QUALITY_CLIPPING_CRITICAL:
            _emit(
                "high_clipping",
                "critical",
                f"Audio clipping critical ({score.avg_clipping_rate:.3f} > "
                f"{s.QUALITY_CLIPPING_CRITICAL:.3f}).",
                score.avg_clipping_rate,
                s.QUALITY_CLIPPING_CRITICAL,
            )
        elif score.avg_clipping_rate > s.QUALITY_CLIPPING_WARNING:
            _emit(
                "high_clipping",
                "warning",
                f"Audio clipping detected ({score.avg_clipping_rate:.3f} > "
                f"{s.QUALITY_CLIPPING_WARNING:.3f}).",
                score.avg_clipping_rate,
                s.QUALITY_CLIPPING_WARNING,
            )

        return warnings
