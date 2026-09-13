"""S64 — visual assembly domain models."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

DEFAULT_TIMESTAMP_THRESHOLD_SECONDS = 300
DEFAULT_SEMANTIC_SIMILARITY_THRESHOLD = 0.70


class AssetType(StrEnum):
    TEXT_DIAGRAM = "text_diagram"
    LICENSED_IMAGE = "licensed_image"
    AI_GENERATED = "ai_generated"
    OCR_UPLOAD = "ocr_upload"
    BOARD_PHOTO = "board_photo"


_TYPE_ORDER = {
    AssetType.TEXT_DIAGRAM: 0,
    AssetType.LICENSED_IMAGE: 1,
    AssetType.AI_GENERATED: 1,
    AssetType.OCR_UPLOAD: 2,
    AssetType.BOARD_PHOTO: 3,
}


class AssetAttachment(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    note_section_id: uuid.UUID
    asset_type: AssetType
    asset_id: uuid.UUID
    ordinal: int = 0
    caption: str | None = None
    width: int | None = None
    height: int | None = None
    render_path: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = {"from_attributes": True}


class BoardPhotoMatch(BaseModel):
    upload_id: uuid.UUID
    note_section_id: uuid.UUID
    match_method: str
    match_confidence: float = Field(..., ge=0.0, le=1.0)
    timestamp_delta_seconds: int | None = None
    semantic_similarity: float | None = None


class AssembledSection(BaseModel):
    note_section_id: uuid.UUID
    heading: str
    body_md: str
    assets: list[AssetAttachment] = Field(default_factory=list)
    board_photos: list[BoardPhotoMatch] = Field(default_factory=list)
    text_diagrams: list[AssetAttachment] = Field(default_factory=list)
    images: list[AssetAttachment] = Field(default_factory=list)
    ocr_text: list[AssetAttachment] = Field(default_factory=list)


class AssembledNoteView(BaseModel):
    session_id: uuid.UUID
    subject_id: uuid.UUID
    sections: list[AssembledSection]
    total_assets: int
    asset_type_breakdown: dict[str, int]
