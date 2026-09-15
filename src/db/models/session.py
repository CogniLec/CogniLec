"""Session model and status enum."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, Float, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from sqlalchemy.types import DateTime, Uuid

from src.db.models.base import Base


class SessionStatus(str, Enum):
    CREATED = "created"
    RECORDING = "recording"
    TRANSCRIBED = "transcribed"
    PROCESSING = "processing"
    COMPLETE = "complete"
    FAILED = "failed"


class Session(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint("session_type IN ('content', 'syllabus', 'mixed')", name="ck_session_type"),
        CheckConstraint(
            "status IN ('created', 'recording', 'transcribed', 'processing', 'complete', 'failed')",
            name="ck_session_status",
        ),
        Index("idx_sessions_subject_id", "subject_id"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    subject_id: Mapped[UUID] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False
    )
    session_type: Mapped[str] = mapped_column(String(50), nullable=False, default="content")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=SessionStatus.CREATED.value
    )
    audio_quality: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes_ready: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
