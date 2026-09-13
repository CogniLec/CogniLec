"""S62 — licensed image retrieval domain models."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field
from src.services.image_retrieval.licence import LicenceCategory

DEFAULT_SCORE_THRESHOLD = 0.50


class ImageSource(BaseModel):
    name: str
    base_url: str
    api_type: str = "rest"
    rate_limit_rpm: int = 60


class RetrievedImage(BaseModel):
    id: str
    source: ImageSource
    source_url: str
    image_url: str
    title: str
    licence: LicenceCategory
    licence_url: str | None = None
    author: str | None = None
    width: int | None = None
    height: int | None = None
    thumbnail_url: str | None = None


class ScoredImage(BaseModel):
    retrieved: RetrievedImage
    text_similarity: float = Field(..., ge=0.0, le=1.0)
    clip_alignment: float = Field(..., ge=0.0, le=1.0)
    composite_score: float = Field(..., ge=0.0, le=1.0)
    accepted: bool = False


class ImageRetrievalResult(BaseModel):
    concept_description: str
    images_retrieved: int
    images_after_licence_filter: int
    images_after_score_filter: int
    accepted_images: list[ScoredImage]
    source_breakdown: dict[str, int]
    best_match: ScoredImage | None = None


class ImageAsset(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    note_section_id: uuid.UUID
    source_url: str
    licence: LicenceCategory
    licence_url: str | None = None
    author: str | None = None
    image_url: str
    thumbnail_url: str | None = None
    composite_score: float
    is_ai_generated: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = {"from_attributes": True}


class AttributionDisplay(BaseModel):
    image_id: uuid.UUID
    source_url: str
    licence: LicenceCategory
    licence_url: str | None
    author: str | None
    attribution_text: str
