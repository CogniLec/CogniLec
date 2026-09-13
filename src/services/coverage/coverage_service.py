"""S52 — coverage computation: cosine-similarity topic-to-syllabus alignment."""

from __future__ import annotations

import uuid

import numpy as np
from src.db.repositories.coverage_repo import CoverageRepository
from src.services.coverage.models import (
    AlignmentConfidence,
    CoverageStatus,
    SyllabusCoverageSummary,
    SyllabusItemCoverageDetail,
    classify_similarity,
)


def _cosine(a: list[float], b: list[float]) -> float:
    va, vb = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    denom = np.linalg.norm(va) * np.linalg.norm(vb)
    if denom == 0:
        return 0.0
    return float(np.dot(va, vb) / denom)


class CoverageService:
    def __init__(self, repo: CoverageRepository) -> None:
        self._repo = repo

    async def recompute_coverage(self, subject_id: uuid.UUID) -> SyllabusCoverageSummary:
        """Recompute all topic-syllabus alignments for a subject.

        Respects existing user corrections (`manually_corrected` items and
        pairs the user explicitly unlinked are never overwritten - T52.4).
        """
        items = await self._repo.get_syllabus_items(subject_id)
        topics = await self._repo.get_topics(subject_id)

        for item in items:
            if item.manually_corrected or item.embedding is None:
                continue

            best_by_topic: dict[uuid.UUID, float] = {}
            for topic in topics:
                if topic.centroid is None:
                    continue
                if self._repo.is_suppressed(subject_id, topic.id, item.id):
                    continue
                sim = _cosine(list(item.embedding), list(topic.centroid))
                pair_confidence = classify_similarity(sim)
                if pair_confidence != AlignmentConfidence.NONE:
                    best_by_topic[topic.id] = sim

            covered_by = list(best_by_topic.keys())
            confidence: AlignmentConfidence | None
            if not covered_by:
                status = CoverageStatus.NOT_STARTED
                confidence = None
            elif any(v >= 0.80 for v in best_by_topic.values()):
                status = CoverageStatus.COVERED
                confidence = AlignmentConfidence.AUTO
            else:
                status = CoverageStatus.PARTIAL
                confidence = AlignmentConfidence.SUGGESTED

            await self._repo.update_item_coverage(item.id, status, covered_by, confidence)

        return await self.get_summary(subject_id)

    async def post_session_update(
        self, subject_id: uuid.UUID, session_id: uuid.UUID
    ) -> SyllabusCoverageSummary:
        """Triggered after session.complete (S52 hook, cadence-agnostic to S53)."""
        return await self.recompute_coverage(subject_id)

    async def get_summary(self, subject_id: uuid.UUID) -> SyllabusCoverageSummary:
        items = await self._repo.get_syllabus_items(subject_id)
        total = len(items)
        covered = sum(1 for i in items if i.coverage_status == CoverageStatus.COVERED.value)
        partial = sum(1 for i in items if i.coverage_status == CoverageStatus.PARTIAL.value)
        not_started = total - covered - partial
        pct = round((covered / total) * 100, 2) if total else 0.0

        details = [
            SyllabusItemCoverageDetail(
                item_id=i.id,
                title=i.title,
                item_type=i.item_type,
                ordinal=i.ordinal,
                parent_id=i.parent_id,
                coverage_status=CoverageStatus(i.coverage_status),
                covered_by_topics=list(i.covered_by or []),
                alignment_confidence=(
                    AlignmentConfidence(i.alignment_confidence) if i.alignment_confidence else None
                ),
            )
            for i in items
        ]
        return SyllabusCoverageSummary(
            subject_id=subject_id,
            total_items=total,
            covered_items=covered,
            partial_items=partial,
            not_started_items=not_started,
            coverage_pct=pct,
            items=details,
        )
