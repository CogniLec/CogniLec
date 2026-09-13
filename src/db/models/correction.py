"""S65 — corrections: append-only training-signal audit trail.

Every human correction (A1 relevance override, topic label edit, topic
split/merge, syllabus alignment correction, image rejection, note edit) is
captured here with the original prediction, the human-corrected value, and
enough context to reconstruct a training example later (S66-S69). Rows are
immutable once written (T65.2) - enforced both by never exposing an
update/delete path in the repository layer and by a DB-level rule
(migration `c4e7f2a9b6d1`) that rejects UPDATE/DELETE outright.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.db.models.base import Base


class Correction(Base):
    __tablename__ = "corrections"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    correction_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    subject_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    # No ON DELETE action (defaults to RESTRICT): deleting a user with
    # corrections referencing them must fail rather than issue an UPDATE
    # against this table - an UPDATE here would collide with the
    # immutability rule below (see migration `c4e7f2a9b6d1`'s docstring).
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    original_value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    corrected_value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    context: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    consent_for_training: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
