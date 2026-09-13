"""S63 — FR-4.9 boundary: the generation request schema has NO image field.

This is the structural half of the hard gate (T63.1). The Semgrep rule
(`.semgrep/rules/fr49_boundary.yaml`, T63.3) is the second, independent
enforcement mechanism — CI-time, not just schema-time.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class GenerationStyle(StrEnum):
    DIAGRAM = "diagram"
    ILLUSTRATION = "illustration"
    SCHEMATIC = "schematic"
    NATURAL = "natural"


class GenerateRequest(BaseModel):
    """Request to generate an image from a text description ONLY.

    FR-4.9: no field named or containing "image" exists on this schema.
    A copyrighted or retrieved image cannot be passed to the generation
    service because there is nowhere to put it.
    """

    concept_description: str = Field(..., min_length=10, max_length=2000)
    subject_id: uuid.UUID
    style_preset: GenerationStyle = GenerationStyle.ILLUSTRATION
    width: int = Field(default=512, ge=256, le=1024)
    height: int = Field(default=512, ge=256, le=1024)
    seed: int | None = None

    @model_validator(mode="after")
    def no_image_parameter(self) -> GenerateRequest:
        image_fields = [f for f in type(self).model_fields if "image" in f.lower()]
        if image_fields:
            msg = f"FR-4.9 violation: image fields not allowed: {image_fields}"
            raise ValueError(msg)
        return self


class GeneratedImage(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    concept_description: str
    image_url: str
    storage_path: str
    width: int
    height: int
    seed: int | None = None
    is_ai_generated: bool = True
    ai_label: str = "AI-generated illustration"
    style_preset: GenerationStyle
    subject_id: uuid.UUID
    created_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = {"from_attributes": True}

    @model_validator(mode="after")
    def always_labelled(self) -> GeneratedImage:
        if not self.is_ai_generated:
            msg = "AC-17/FR-4.10 violation: is_ai_generated must always be True"
            raise ValueError(msg)
        return self


class GenerationResult(BaseModel):
    generated: GeneratedImage | None = None
    cached: bool = False
    cache_hit_id: uuid.UUID | None = None
    generation_time_ms: int | None = None
    concept_description: str
