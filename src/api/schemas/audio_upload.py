"""Audio file upload API schemas."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class AudioFileUploadResponse(BaseModel):
    session_id: uuid.UUID
    filename: str
    total_chunks: int
    status: str = Field(
        ...,
        description="Upload status: 'accepted' if file was accepted for processing",
    )
    message: str = Field(
        default="Audio file accepted. Processing will begin shortly.",
        description="Human-readable status message",
    )
