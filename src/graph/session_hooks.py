"""S52/S53 — post-session hook: coverage recompute + syllabus-seeded re-cluster."""

from __future__ import annotations

import uuid

from src.services.clustering.recluster import ReclusterService
from src.services.coverage.coverage_service import CoverageService


async def on_session_complete(
    session_id: uuid.UUID,
    subject_id: uuid.UUID,
    session_number: int,
    coverage_service: CoverageService,
    recluster_service: ReclusterService,
    new_topic_embeddings: list[list[float]] | None = None,
) -> None:
    """Post-session hook: triggers coverage update (S52) and re-clustering (S53)."""
    await coverage_service.post_session_update(subject_id, session_id)

    if new_topic_embeddings and await recluster_service.should_recluster(
        subject_id, session_number
    ):
        await recluster_service.recluster(subject_id, new_topic_embeddings)
