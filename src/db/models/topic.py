"""Topic model - partitioned by subject_id (S30)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import ARRAY, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.db.models.base import Base


class Topic(Base):
    __tablename__ = "topics"

    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=True
    )
    centroid = mapped_column(Vector(1024), nullable=False)
    label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    keywords: Mapped[list[str] | None] = mapped_column(ARRAY(Text()), nullable=True)
    keyword_scores: Mapped[list[float] | None] = mapped_column(ARRAY(Float()), nullable=True)
    segment_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    utterance_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    is_user_edited: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    provisional: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
