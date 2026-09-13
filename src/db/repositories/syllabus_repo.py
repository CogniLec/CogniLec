"""Syllabus repository.

Two access paths, per S11 (reconciling the spec's write methods with its
read-only FDW requirement, per S50's "A6 is sole writer to DB-3"):

- ``SyllabusRepository`` writes (create_item/update_coverage/delete_item)
  and single-item/tree reads go through a DIRECT connection to PG-SYLLABUS
  (``src.db.session.get_syllabus_session``). This is the only path that
  ever writes to syllabus_items.
- ``get_subject_syllabus`` is a READ-THROUGH query via the ``syllabus_items``
  foreign table on PG-MAIN (created by the S11 alembic migration,
  a2c7d4e9f1b3), for joining local ``subjects`` rows with foreign
  ``syllabus_items`` rows in one query (spec section 5's FDW Query
  Pattern; T11.2/T11.3). It takes a PG-MAIN session, never a PG-SYLLABUS
  one, and is read-only both by convention and because the FDW user
  mapping itself only has SELECT on the remote table (T11.5).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import CursorResult, text
from sqlalchemy.ext.asyncio import AsyncSession


class SyllabusRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_item(
        self, subject_id: uuid.UUID, data: dict[str, object]
    ) -> dict[str, object]:
        """Create a syllabus item on PG-SYLLABUS."""
        result = await self._session.execute(
            text("""
                INSERT INTO syllabus_items (subject_id, parent_id, ordinal, title, description,
                                           source, source_session_id)
                VALUES (:subject_id, :parent_id, :ordinal, :title, :description,
                        :source, :source_session_id)
                RETURNING id
            """),
            {"subject_id": subject_id, **data},
        )
        await self._session.flush()
        row = result.fetchone()
        return {"id": row[0]} if row else {}

    async def get_tree(self, subject_id: uuid.UUID) -> list[dict[str, object]]:
        """Get full syllabus tree for a subject."""
        result = await self._session.execute(
            text("""
                SELECT * FROM syllabus_items
                WHERE subject_id = :subject_id
                ORDER BY ordinal
            """),
            {"subject_id": subject_id},
        )
        return [dict(row._mapping) for row in result.fetchall()]

    async def get_item(self, item_id: uuid.UUID) -> dict[str, object] | None:
        """Get a single syllabus item."""
        result = await self._session.execute(
            text("SELECT * FROM syllabus_items WHERE id = :id"),
            {"id": item_id},
        )
        row = result.fetchone()
        return dict(row._mapping) if row else None

    async def update_coverage(
        self,
        item_id: uuid.UUID,
        status: str,
        topic_ids: list[uuid.UUID],
    ) -> dict[str, object] | None:
        """Update coverage status and linked topic IDs."""
        result = await self._session.execute(
            text("""
                UPDATE syllabus_items
                SET coverage_status = :status, covered_by = :topic_ids, updated_at = now()
                WHERE id = :id
                RETURNING *
            """),
            {"id": item_id, "status": status, "topic_ids": topic_ids},
        )
        await self._session.flush()
        row = result.fetchone()
        return dict(row._mapping) if row else None

    async def delete_item(self, item_id: uuid.UUID) -> bool:
        """Delete a syllabus item."""
        raw = await self._session.execute(
            text("DELETE FROM syllabus_items WHERE id = :id"),
            {"id": item_id},
        )
        result: CursorResult[Any] = raw  # type: ignore[assignment]
        await self._session.flush()
        return bool(result.rowcount > 0)


class SyllabusFdwReader:
    """Read-through FDW queries from PG-MAIN (T11.2/T11.3).

    Takes a PG-MAIN ``AsyncSession`` (e.g. from
    ``src.db.session.get_main_session``) and queries the ``syllabus_items``
    foreign table created by migration a2c7d4e9f1b3, optionally joined
    against the local ``subjects`` table. Never writes - the FDW user
    mapping itself is SELECT-only (T11.5), so any write attempted through
    this path fails at the database level regardless.
    """

    def __init__(self, main_session: AsyncSession) -> None:
        self._session = main_session

    async def get_items_for_subject(self, subject_id: uuid.UUID) -> list[dict[str, object]]:
        """Query the foreign table directly (T11.2): rows for one subject."""
        result = await self._session.execute(
            text("""
                SELECT * FROM syllabus_items
                WHERE subject_id = :subject_id
                ORDER BY ordinal
            """),
            {"subject_id": subject_id},
        )
        return [dict(row._mapping) for row in result.fetchall()]

    async def get_subject_syllabus(self, subject_id: uuid.UUID) -> list[dict[str, object]]:
        """Join local ``subjects`` with foreign ``syllabus_items`` (T11.3).

        Mirrors the spec's FDW Query Pattern (section 5).
        """
        result = await self._session.execute(
            text("""
                SELECT
                    s.id AS subject_id,
                    s.name AS subject_name,
                    si.id AS item_id,
                    si.parent_id,
                    si.ordinal,
                    si.title,
                    si.description,
                    si.source,
                    si.source_session_id,
                    si.coverage_status,
                    si.covered_by,
                    si.created_at,
                    si.updated_at
                FROM subjects s
                JOIN syllabus_items si ON si.subject_id = s.id
                WHERE s.id = :subject_id
                ORDER BY si.ordinal
            """),
            {"subject_id": subject_id},
        )
        return [dict(row._mapping) for row in result.fetchall()]
