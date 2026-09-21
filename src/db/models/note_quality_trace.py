"""Append-only per-session note-quality scores (self-improving loop, Stage 1).

Immutable like `corrections`: a DB rule rejects UPDATE/DELETE (migration
`d1a7c3e5b9f2`). Rows hold scores only, never transcript text.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.db.models.base import Base


class NoteQualityTrace(Base):
    __tablename__ = "note_quality_traces"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    subject_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reward: Mapped[float] = mapped_column(Float, nullable=False)
    terms: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    judged: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    config_version: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
