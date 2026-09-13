"""S59 — post-session upload API schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from src.services.uploads.models import FileType, UploadStatus


class UploadCreate(BaseModel):
    session_id: uuid.UUID
    subject_id: uuid.UUID
    description: str | None = Field(None, max_length=500)


class UploadResponse(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    subject_id: uuid.UUID
    file_type: FileType
    original_filename: str
    storage_path: str
    status: UploadStatus
    exif_stripped: bool
    phash: str | None = None
    is_duplicate: bool = False
    merged_asset_id: uuid.UUID | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class UploadListResponse(BaseModel):
    items: list[UploadResponse]
    total: int
