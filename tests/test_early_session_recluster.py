"""Tests for S53 T53.4 — tight re-cluster cadence for sessions 2-5."""

from __future__ import annotations

import uuid

from src.services.clustering.recluster import (
    NORMAL_CADENCE_INTERVAL,
    TIGHT_CADENCE_SESSIONS,
    ReclusterService,
)
from src.services.clustering.seed import CentroidSeedService


class _StubRepo:
    async def list_for_subject(self, subject_id):
        return []


async def test_sessions_2_5_recluster() -> None:
    seed_service = CentroidSeedService(_StubRepo())
    recluster_service = ReclusterService(seed_service)
    subject_id = uuid.uuid4()

    assert await recluster_service.should_recluster(subject_id, 1) is False
    for session_number in range(2, TIGHT_CADENCE_SESSIONS + 1):
        assert await recluster_service.should_recluster(subject_id, session_number) is True

    # Session 6 (first past the tight window): does not recluster unless
    # the normal interval boundary is hit.
    assert await recluster_service.should_recluster(subject_id, TIGHT_CADENCE_SESSIONS + 1) is False
    boundary = TIGHT_CADENCE_SESSIONS + NORMAL_CADENCE_INTERVAL
    assert await recluster_service.should_recluster(subject_id, boundary) is True
