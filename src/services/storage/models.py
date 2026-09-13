"""Pydantic models for the object storage service (S14)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field


class BucketName(StrEnum):
    """The five provisioned MinIO buckets."""

    AUDIO = "lis-audio"
    UPLOADS = "lis-uploads"
    GENERATED = "lis-generated"
    EXPORTS = "lis-exports"
    EVAL = "lis-eval"


class PresignedURLRequest(BaseModel):
    """Request body for POST /presigned-url."""

    session_id: UUID
    bucket: BucketName
    key: str = Field(..., min_length=1, description="Object key within bucket")
    expires_in: int = Field(default=3600, ge=60, le=86400, description="URL TTL in seconds")
    content_type: str | None = None


class PresignedURLResponse(BaseModel):
    """Response body for POST /presigned-url."""

    upload_url: str
    key: str
    bucket: str
    expires_at: datetime


class ObjectMetadata(BaseModel):
    """Metadata describing a stored object."""

    bucket: str
    key: str
    size: int
    etag: str
    last_modified: datetime
