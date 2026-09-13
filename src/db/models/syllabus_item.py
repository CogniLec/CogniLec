"""Syllabus item model - lives on PG-SYLLABUS, accessed via FDW.

IMPORTANT: this model uses its own declarative base (``SyllabusBase``),
*not* the shared ``src.db.models.base.Base`` used by every PG-MAIN model.
``syllabus_items`` physically lives on PG-SYLLABUS (created out-of-band via
docker/postgres/migrations/syllabus/001_syllabus_items.sql, applied by
scripts/s11_apply_syllabus_schema.py) and is only ever *read* on PG-MAIN
through the ``syllabus_items`` foreign table created by the S11 FDW
migration. If this model were registered on the shared ``Base.metadata``,
alembic autogenerate on PG-MAIN (src/db/migrations/env.py, which sets
``target_metadata = Base.metadata``) would try to manage/create a *local*
``syllabus_items`` table on PG-MAIN too - which would collide with the FDW
foreign table of the same name. Keeping it on a separate base excludes it
from PG-MAIN's autogenerate scope entirely.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, Float, Integer, MetaData, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Deliberately NOT src.db.models.base.Base - see module docstring.
_syllabus_convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class SyllabusBase(DeclarativeBase):
    """Declarative base for PG-SYLLABUS-only models.

    Intentionally excluded from src/db/migrations/env.py's
    ``target_metadata`` (which only wires up ``src.db.models.base.Base``),
    so PG-MAIN's alembic autogenerate never attempts to manage this table.
    """

    metadata = MetaData(naming_convention=_syllabus_convention)


class SyllabusItem(SyllabusBase):
    __tablename__ = "syllabus_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    subject_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding = mapped_column(Vector(1024), nullable=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="lecture")
    source_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    coverage_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="not_started"
    )
    covered_by: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, default=list
    )
    # S50/S52 additions (002_syllabus_items_extend.sql).
    item_type: Mapped[str] = mapped_column(String(20), nullable=False, default="topic")
    weight_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    week_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    syllabus_references: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list
    )
    manually_corrected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    alignment_confidence: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
