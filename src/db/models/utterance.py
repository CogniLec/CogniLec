"""Utterance model - partitioned by subject_id."""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.db.models.base import Base


class Utterance(Base):
    __tablename__ = "utterances"
    __table_args__ = (
        UniqueConstraint("subject_id", "session_id", "seq", name="uq_utterance_session_seq"),
    )

    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=sa_text("gen_random_uuid()")
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    asr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    words: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default=sa_text("'[]'::jsonb")
    )
    speaker_tag: Mapped[str | None] = mapped_column(String(10), nullable=True)
    embedding = mapped_column(Vector(1024), nullable=True)
    embed_model_ver: Mapped[str] = mapped_column(String(50), nullable=False)
    topic_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    is_relevant: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    filter_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    outlier_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    asr_agreement: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=sa_text("now()")
    )
