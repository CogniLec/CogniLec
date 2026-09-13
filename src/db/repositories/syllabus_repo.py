"""Syllabus repository.

Two access paths, per S11 (reconciling the spec's write methods with its
read-only FDW requirement, per S50's "A6 is sole writer to DB-3"):

- ``SyllabusRepository`` writes and single-item/tree reads go through a
  DIRECT connection to PG-SYLLABUS (``src.db.session.get_syllabus_session``).
  This is the only path that ever writes to syllabus_items.
- ``get_subject_syllabus`` is a READ-THROUGH query via the ``syllabus_items``
  foreign table on PG-MAIN (created by the S11 alembic migration,
  a2c7d4e9f1b3), for joining local ``subjects`` rows with foreign
  ``syllabus_items`` rows in one query (spec section 5's FDW Query
  Pattern; T11.2/T11.3). It takes a PG-MAIN session, never a PG-SYLLABUS
  one, and is read-only both by convention and because the FDW user
  mapping itself only has SELECT on the remote table (T11.5).

S50 adds ``bulk_create_items``/``upsert_item``: the A6 extraction write
path, gated by ``DB3WriteGuard.check_write_authority()`` (FR-3.8). The
original ``create_item``/``update_coverage``/``delete_item`` methods are
left UNGATED - they predate S50, are exercised by tests/test_syllabus.py's
S11 suite with ``source="manual"`` writes, and represent the
manual/administrative write path rather than the A6 lecture-extraction
path FR-3.8 is scoped to.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from config.schemas.a6_syllabus import MAX_HIERARCHY_DEPTH, ExtractedSyllabusItem
from sqlalchemy import CursorResult, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.syllabus_item import SyllabusItem
from src.db.write_guard import DB3WriteGuard


@dataclass
class SyllabusTree:
    subject_id: uuid.UUID
    items: list[SyllabusItem] = field(default_factory=list)


class SyllabusRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # -- S11 original raw-SQL methods (manual/administrative write path) --

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

    # -- S50 A6 write-authority-gated ORM path --

    async def bulk_create_items(
        self,
        subject_id: uuid.UUID,
        items: list[ExtractedSyllabusItem],
        source_session_id: uuid.UUID | None = None,
        source: str = "lecture",
    ) -> list[SyllabusItem]:
        """Bulk insert syllabus items into PG-SYLLABUS (write-authority enforced)."""
        DB3WriteGuard.check_write_authority()
        deduped = _deduplicate_by_title_and_parent(items)
        ordinal_to_id: dict[int, uuid.UUID] = {}
        created: list[SyllabusItem] = []
        for item in deduped:
            parent_id = (
                ordinal_to_id.get(item.parent_ordinal)
                if item.parent_ordinal is not None
                else None
            )
            row = SyllabusItem(
                subject_id=subject_id,
                parent_id=parent_id,
                ordinal=item.ordinal,
                title=item.title,
                description=item.description,
                item_type=item.item_type.value,
                weight_pct=item.weight_pct,
                week_number=item.week_number,
                syllabus_references=item.references,
                source=source,
                source_session_id=source_session_id,
            )
            self._session.add(row)
            await self._session.flush()
            ordinal_to_id[item.ordinal] = row.id
            created.append(row)
        return created

    async def upsert_item(
        self,
        subject_id: uuid.UUID,
        item: ExtractedSyllabusItem,
        source_session_id: uuid.UUID | None = None,
    ) -> SyllabusItem:
        """Upsert a single item (update if title + parent ordinal match)."""
        DB3WriteGuard.check_write_authority()
        parent_id = None
        if item.parent_ordinal is not None:
            parent = await self._get_by_ordinal(subject_id, item.parent_ordinal)
            parent_id = parent.id if parent else None

        existing = await self._get_by_title_and_parent(subject_id, item.title, parent_id)
        if existing is not None:
            existing.description = item.description or existing.description
            existing.weight_pct = item.weight_pct
            existing.week_number = item.week_number
            existing.syllabus_references = item.references
            await self._session.flush()
            return existing

        row = SyllabusItem(
            subject_id=subject_id,
            parent_id=parent_id,
            ordinal=item.ordinal,
            title=item.title,
            description=item.description,
            item_type=item.item_type.value,
            weight_pct=item.weight_pct,
            week_number=item.week_number,
            syllabus_references=item.references,
            source_session_id=source_session_id,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def get_tree(self, subject_id: uuid.UUID) -> Any:
        """Get full syllabus tree for a subject.

        Returns a list of raw-mapping dicts (S11 shape) for
        ``source_session_id`` unaware callers, matching the pre-S50
        contract that tests/test_syllabus.py asserts against.
        """
        result = await self._session.execute(
            text("""
                SELECT * FROM syllabus_items
                WHERE subject_id = :subject_id
                ORDER BY ordinal
            """),
            {"subject_id": subject_id},
        )
        return [dict(row._mapping) for row in result.fetchall()]

    async def get_orm_tree(self, subject_id: uuid.UUID) -> SyllabusTree:
        """S50/S52 ORM-typed tree read, used by coverage/seed services."""
        result = await self._session.execute(
            select(SyllabusItem)
            .where(SyllabusItem.subject_id == subject_id)
            .order_by(SyllabusItem.ordinal)
        )
        return SyllabusTree(subject_id=subject_id, items=list(result.scalars().all()))

    async def list_for_subject(self, subject_id: uuid.UUID) -> list[SyllabusItem]:
        return (await self.get_orm_tree(subject_id)).items

    async def _get_by_ordinal(self, subject_id: uuid.UUID, ordinal: int) -> SyllabusItem | None:
        result = await self._session.execute(
            select(SyllabusItem).where(
                SyllabusItem.subject_id == subject_id, SyllabusItem.ordinal == ordinal
            )
        )
        return result.scalars().first()

    async def _get_by_title_and_parent(
        self, subject_id: uuid.UUID, title: str, parent_id: uuid.UUID | None
    ) -> SyllabusItem | None:
        result = await self._session.execute(
            select(SyllabusItem).where(
                SyllabusItem.subject_id == subject_id,
                SyllabusItem.title == title,
                SyllabusItem.parent_id.is_(parent_id)
                if parent_id is None
                else SyllabusItem.parent_id == parent_id,
            )
        )
        return result.scalars().first()


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
                    si.item_type,
                    si.weight_pct,
                    si.week_number,
                    si.syllabus_references,
                    si.source,
                    si.source_session_id,
                    si.coverage_status,
                    si.covered_by,
                    si.manually_corrected,
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


def _deduplicate_by_title_and_parent(
    items: list[ExtractedSyllabusItem],
) -> list[ExtractedSyllabusItem]:
    """Same ordinal+parent+title = merge descriptions; re-index ordinals sequentially."""
    seen: dict[tuple[int | None, str], ExtractedSyllabusItem] = {}
    order: list[tuple[int | None, str]] = []
    for item in items:
        key = (item.parent_ordinal, item.title)
        if key in seen:
            existing = seen[key]
            merged_desc = (
                "; ".join(d for d in (existing.description, item.description) if d) or None
            )
            seen[key] = existing.model_copy(update={"description": merged_desc})
        else:
            seen[key] = item
            order.append(key)

    result = [seen[k] for k in order]
    by_parent: dict[int | None, int] = {}
    reindexed: list[ExtractedSyllabusItem] = []
    ordinal_remap: dict[int, int] = {}
    for item in result:
        parent_ord = (
            ordinal_remap.get(item.parent_ordinal) if item.parent_ordinal is not None else None
        )
        next_ordinal = by_parent.get(parent_ord, 0)
        by_parent[parent_ord] = next_ordinal + 1
        ordinal_remap[item.ordinal] = next_ordinal
        reindexed.append(
            item.model_copy(update={"ordinal": next_ordinal, "parent_ordinal": parent_ord})
        )
    return reindexed


__all__ = [
    "MAX_HIERARCHY_DEPTH",
    "SyllabusFdwReader",
    "SyllabusRepository",
    "SyllabusTree",
]
