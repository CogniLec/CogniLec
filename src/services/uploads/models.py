"""S59 — post-session upload domain models."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class UploadStatus(StrEnum):
    UPLOADED = "uploaded"
    STRIPPING = "stripping"
    STRIPPED = "stripped"
    DEDUP_CHECK = "dedup_check"
    UNIQUE = "unique"
    DUPLICATE = "duplicate"
    READY_FOR_OCR = "ready_for_ocr"
    FAILED = "failed"


class FileType(StrEnum):
    IMAGE = "image"
    PDF = "pdf"
    MULTI_PAGE_PDF = "multi_page_pdf"


ALLOWED_IMAGE_TYPES = ("image/jpeg", "image/png", "image/webp", "image/heic")
ALLOWED_PDF_TYPES = ("application/pdf",)
DEFAULT_MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024
DEFAULT_PHASH_HAMMING_THRESHOLD = 8


class UploadRecord(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    subject_id: uuid.UUID
    file_type: FileType
    original_filename: str
    storage_path: str
    status: UploadStatus
    exif_stripped: bool = False
    phash: str | None = None
    is_duplicate: bool = False
    merged_asset_id: uuid.UUID | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
