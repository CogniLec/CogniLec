"""Pydantic schemas – Session."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from src.db.models.session import SessionStatus


class SessionCreate(BaseModel):
    subject_id: uuid.UUID
    session_type: Literal["content", "syllabus", "mixed"] = "content"


class SessionUpdate(BaseModel):
    status: SessionStatus


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    subject_id: uuid.UUID
    session_type: str
    status: SessionStatus
    audio_quality: float | None
    notes_ready: bool
    created_at: datetime
    updated_at: datetime
