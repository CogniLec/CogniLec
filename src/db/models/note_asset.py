"""Note asset model - images, OCR, diagrams (NOT partitioned)."""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.db.models.base import Base


class AssetType(StrEnum):
    WEB_IMAGE = "web_image"
    GENERATED_IMAGE = "generated_image"
    BOARD_PHOTO = "board_photo"
    OCR_TEXT = "ocr_text"
    DIAGRAM = "diagram"


class NoteAsset(Base):
    __tablename__ = "note_assets"
    __table_args__ = (
        CheckConstraint(
            "(asset_type != 'web_image') OR (source_url IS NOT NULL AND licence IS NOT NULL)",
            name="ck_web_image_licence",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    note_section_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    asset_type: Mapped[AssetType] = mapped_column(String(50), nullable=False)
    object_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    licence: Mapped[str | None] = mapped_column(String(100), nullable=True)
    match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_ai_generated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ocr_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
