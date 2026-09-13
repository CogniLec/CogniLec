"""Domain schemas for the audio pre-processing chain (S17)."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field


class ChainStage(StrEnum):
    """Processing chain state machine (spec section 2)."""

    RECEIVED = "RECEIVED"
    RESAMPLED = "RESAMPLED"
    DENOISED = "DENOISED"
    VAD_PROCESSED = "VAD_PROCESSED"
    EMITTED = "EMITTED"
    FAILED = "FAILED"


class VADRegion(BaseModel):
    """A single detected speech region within a processed chunk."""

    start_ms: int = Field(..., ge=0)
    end_ms: int = Field(..., ge=0)
    confidence: float = Field(..., ge=0.0, le=1.0)


class ProcessedChunk(BaseModel):
    """Output of the pre-processing chain for one audio chunk."""

    session_id: UUID
    sequence: int
    original_sample_rate: int
    output_sample_rate: int = 16000
    output_channels: int = 1
    duration_ms: int
    audio_data: bytes  # 16kHz mono float32 PCM (WAV container bytes)
    vad_regions: list[VADRegion]
    speech_ratio: float = Field(..., ge=0.0, le=1.0)
    has_speech: bool
    processing_latency_ms: int


class PreprocessingResult(BaseModel):
    """Full result of running one chunk through the chain, with diagnostics."""

    chunk: ProcessedChunk
    lufs_before: float | None = None
    lufs_after: float | None = None
    snr_before: float | None = None
    snr_after: float | None = None
    denoise_applied: bool
