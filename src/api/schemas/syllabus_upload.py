"""S51 — Pydantic models for the syllabus upload endpoint."""

from __future__ import annotations

import uuid
from enum import StrEnum

from pydantic import BaseModel, Field


class UploadFormat(StrEnum):
    PDF = "pdf"
    IMAGE = "image"
    TEXT = "text"
    UNKNOWN = "unknown"


class SyllabusUploadResponse(BaseModel):
    upload_id: uuid.UUID
    status: str
    items_extracted: int | None = None
    message: str
    error_details: str | None = None


class ParsedSyllabusItem(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    item_type: str = Field(..., pattern="^(module|topic|subtopic|assessment|reference|schedule)$")
    ordinal: int = Field(..., ge=0)
    parent_ordinal: int | None = Field(None, ge=0)
    description: str | None = Field(None, max_length=5000)
    weight_pct: float | None = Field(None, ge=0.0, le=100.0)
    week_number: int | None = Field(None, ge=1)
    references: list[str] = Field(default_factory=list, max_length=20)


class ParsedSyllabus(BaseModel):
    items: list[ParsedSyllabusItem]
    subject_title: str = Field(..., min_length=1, max_length=500)
    total_pages: int | None = None
    parsing_confidence: float = Field(..., ge=0.0, le=1.0)
