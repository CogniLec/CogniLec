"""S60 — OCR domain models."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class OCRServiceType(StrEnum):
    PADDLE_OCR = "paddle_ocr"
    VLM_OCR = "vlm_ocr"
    DOTS_OCR = "dots_ocr"


class OCRConfidenceLevel(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    DISAGREEMENT = "disagreement"


DEFAULT_CONFIDENCE_HIGH = 0.85
DEFAULT_CONFIDENCE_LOW = 0.60
DEFAULT_DISAGREEMENT_THRESHOLD = 0.3


class OCRResult(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    upload_id: uuid.UUID
    service_used: OCRServiceType
    extracted_text: str = Field(..., max_length=50000)
    confidence: float = Field(..., ge=0.0, le=1.0)
    confidence_level: OCRConfidenceLevel
    is_low_confidence: bool = False
    disagreement_flag: bool = False
    paddle_text: str | None = None
    vlm_text: str | None = None
    paddle_confidence: float | None = None
    vlm_confidence: float | None = None
    preprocessing_applied: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
