"""Pydantic schemas - Transcript read API (S24)."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field

from src.db.models.session import SessionStatus


class WordTimestamp(BaseModel):
    word: str
    start_ms: int = Field(..., ge=0)
    end_ms: int = Field(..., ge=0)


class TranscriptUtterance(BaseModel):
    id: uuid.UUID
    seq: int
    start_ms: int
    end_ms: int
    text: str
    asr_confidence: float | None
    asr_agreement: float | None
    speaker_tag: str | None
    is_relevant: bool | None
    filter_reason: str | None
    word_timestamps: list[dict[str, Any]] = Field(default_factory=list)

    @classmethod
    def from_model(cls, utt: Any) -> TranscriptUtterance:
        return cls(
            id=utt.id,
            seq=utt.seq,
            start_ms=utt.start_ms,
            end_ms=utt.end_ms,
            text=utt.text,
            asr_confidence=utt.asr_confidence,
            asr_agreement=utt.asr_agreement,
            speaker_tag=utt.speaker_tag,
            is_relevant=utt.is_relevant,
            filter_reason=utt.filter_reason,
            word_timestamps=utt.words or [],
        )


class TranscriptResponse(BaseModel):
    session_id: uuid.UUID
    subject_id: uuid.UUID
    total_utterances: int
    filtered_count: int
    offset: int
    limit: int
    utterances: list[TranscriptUtterance]
    audio_url: str | None
    session_status: SessionStatus
    notes_ready: bool
