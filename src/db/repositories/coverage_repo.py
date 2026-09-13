"""S52 — coverage repository.

Reads join local topics (PG-MAIN) with syllabus items; per the S52 gotcha
("FDW is READ-ONLY from PG-MAIN"), all coverage/alignment WRITES go
through a direct PG-SYLLABUS connection (the same one `SyllabusRepository`
uses), never through the FDW foreign table.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.syllabus_item import SyllabusItem
from src.db.models.topic import Topic
from src.services.coverage.models import AlignmentConfidence, AlignmentCorrection, CoverageStatus

# User corrections are tracked in-process per subject so that a subsequent
# automatic recompute can suppress the pairs a user explicitly rejected -
# see docs/gaps.md gap #9 for why this isn't yet a dedicated DB-3 table.
_SUPPRESSED_PAIRS: dict[uuid.UUID, set[tuple[uuid.UUID, uuid.UUID]]] = {}


class CoverageRepository:
    def __init__(
        self, syllabus_session: AsyncSession, main_session: AsyncSession | None = None
    ) -> None:
        self._syllabus_session = syllabus_session
        self._main_session = main_session or syllabus_session

    async def get_syllabus_items(self, subject_id: uuid.UUID) -> list[SyllabusItem]:
        result = await self._syllabus_session.execute(
            select(SyllabusItem)
            .where(SyllabusItem.subject_id == subject_id)
            .order_by(SyllabusItem.ordinal)
        )
        return list(result.scalars().all())

    async def get_topics(self, subject_id: uuid.UUID) -> list[Topic]:
        result = await self._main_session.execute(
            select(Topic).where(Topic.subject_id == subject_id)
        )
        return list(result.scalars().all())

    async def update_item_coverage(
        self,
        item_id: uuid.UUID,
        status: CoverageStatus,
        covered_by: list[uuid.UUID],
        confidence: AlignmentConfidence | None,
    ) -> None:
        """Direct PG-SYLLABUS write (never via FDW)."""
        item = await self._syllabus_session.get(SyllabusItem, item_id)
        if item is None or item.manually_corrected:
            return
        item.coverage_status = status.value
        item.covered_by = covered_by
        item.alignment_confidence = confidence.value if confidence else None
        await self._syllabus_session.flush()

    async def persist_user_correction(
        self, subject_id: uuid.UUID, correction: AlignmentCorrection
    ) -> None:
        """Apply a user correction; mark the item manually_corrected so future
        automatic recompute does not silently overwrite it (T52.4)."""
        item = await self._syllabus_session.get(SyllabusItem, correction.syllabus_item_id)
        if item is None:
            return

        covered_by = set(item.covered_by or [])
        if correction.action == "link":
            covered_by.add(correction.topic_id)
        elif correction.action == "unlink":
            covered_by.discard(correction.topic_id)
            _SUPPRESSED_PAIRS.setdefault(subject_id, set()).add(
                (correction.topic_id, correction.syllabus_item_id)
            )
        elif correction.action == "replace" and correction.replace_with_item_id:
            covered_by.discard(correction.topic_id)
            new_item = await self._syllabus_session.get(
                SyllabusItem, correction.replace_with_item_id
            )
            if new_item is not None:
                new_item.covered_by = list({*(new_item.covered_by or []), correction.topic_id})
                new_item.manually_corrected = True
                new_item.coverage_status = CoverageStatus.COVERED.value

        item.covered_by = list(covered_by)
        item.manually_corrected = True
        item.coverage_status = (
            CoverageStatus.COVERED.value if covered_by else CoverageStatus.NOT_STARTED.value
        )
        await self._syllabus_session.flush()

    def is_suppressed(self, subject_id: uuid.UUID, topic_id: uuid.UUID, item_id: uuid.UUID) -> bool:
        return (topic_id, item_id) in _SUPPRESSED_PAIRS.get(subject_id, set())
