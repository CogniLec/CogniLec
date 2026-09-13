"""Pydantic schemas for the ASR worker (S19 spec section 2)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class WordTimestamp(BaseModel):
    """A single word with millisecond-resolution timing and confidence."""

    word: str
    start_ms: int = Field(..., ge=0)
    end_ms: int = Field(..., ge=0)
    confidence: float = Field(..., ge=0.0, le=1.0)


class Utterance(BaseModel):
    """One transcribed utterance (segment) within a session."""

    session_id: UUID
    subject_id: UUID
    sequence: int  # utterance sequence within session
    text: str
    start_ms: int = Field(..., ge=0)
    end_ms: int = Field(..., ge=0)
    confidence: float = Field(..., ge=0.0, le=1.0)
    words: list[WordTimestamp]
    embed_model_ver: str  # from config
    speaker_tag: str | None = None  # set by S20 diarisation
    created_at: datetime


class ASRResult(BaseModel):
    """Result of transcribing one audio chunk."""

    session_id: UUID
    utterances: list[Utterance]
    total_duration_ms: int
    processing_time_ms: int
    real_time_factor: float  # processing_time / total_duration
    model_name: str
    model_quantization: str
