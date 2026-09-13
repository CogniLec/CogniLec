"""S56 — A3 cross-session relationship links, surfaced as note cross-references.

Not partitioned by subject_id like utterances/topics/note_sections (S08):
Block 10's time budget doesn't cover extending `PartitionProvisioner`
(`src/db/partitions/config.py`'s `PARTITIONED_TABLES`) for four new tables,
so this is a plain FK-indexed table instead - a real simplification, not a
fabricated capability (same trade-off S52/S53 made for their own new state,
see docs/gaps.md #9).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.db.models.base import Base


class NoteLinkType:
    BUILDS_ON = "builds_on"
    REVISITS = "revisits"
    CONTRADICTS = "contradicts"
    PREREQUISITE_FOR = "prerequisite_for"

    ALL = (BUILDS_ON, REVISITS, CONTRADICTS, PREREQUISITE_FOR)


class NoteLink(Base):
    __tablename__ = "note_links"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    subject_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subjects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    from_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    to_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    link_type: Mapped[str] = mapped_column(String(30), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
