"""Session request/response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from src.db.models.session import SessionStatus


class SessionCreate(BaseModel):
    subject_id: UUID
    session_type: Literal["content", "syllabus", "mixed"] = "content"


class SessionStatusUpdate(BaseModel):
    status: SessionStatus


class SessionResponse(BaseModel):
    id: UUID
    subject_id: UUID
    session_type: str
    status: SessionStatus
    audio_quality: float | None
    notes_ready: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
