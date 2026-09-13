"""Domain schemas for audio quality metrics & warnings (S18)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ChunkQualityMetrics(BaseModel):
    """Per-chunk audio quality metrics."""

    session_id: UUID
    sequence: int
    snr_db: float = Field(..., description="Signal-to-noise ratio in dB")
    speech_ratio: float = Field(..., ge=0.0, le=1.0, description="Fraction of chunk with speech")
    clipping_rate: float = Field(
        ..., ge=0.0, le=1.0, description="Fraction of samples at max amplitude"
    )
    lufs: float | None = Field(None, description="Integrated loudness")
    rms_db: float | None = None
    computed_at: datetime


class SessionQualityScore(BaseModel):
    """Aggregated rolling-window quality score for a session."""

    session_id: UUID
    avg_snr_db: float
    avg_speech_ratio: float
    avg_clipping_rate: float
    overall_score: float = Field(..., ge=0.0, le=1.0, description="0=worst, 1=best")
    chunk_count: int
    window_snr_db: float = Field(..., description="Rolling window SNR")
    status: str = "normal"  # normal, degraded, warning, critical
    last_updated: datetime


class QualityWarning(BaseModel):
    """An operator-facing warning emitted when quality crosses a threshold."""

    session_id: UUID
    warning_type: str  # "low_snr", "low_speech_ratio", "high_clipping"
    severity: str  # "degraded", "warning", "critical"
    message: str
    metric_value: float
    threshold: float
    timestamp: datetime
