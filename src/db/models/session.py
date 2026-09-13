"""Session model with status enum."""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.db.models.base import Base


class SessionStatus(StrEnum):
    CREATED = "created"
    RECORDING = "recording"
    TRANSCRIBED = "transcribed"
    PROCESSING = "processing"
    COMPLETE = "complete"
    FAILED = "failed"


class Session(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint(
            "session_type IN ('content', 'syllabus', 'mixed')",
            name="ck_session_type",
        ),
        CheckConstraint(
            "status IN ('created', 'recording', 'transcribed', 'processing', 'complete', 'failed')",
            name="ck_session_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    subject_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subjects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    session_type: Mapped[str] = mapped_column(String(50), nullable=False, default="content")
    status: Mapped[SessionStatus] = mapped_column(
        String(20), nullable=False, default=SessionStatus.CREATED
    )
    audio_quality: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes_ready: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    failure_stage: Mapped[str | None] = mapped_column(String(50), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
