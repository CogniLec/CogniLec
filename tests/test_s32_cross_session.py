"""Tests for S32 - cross-session topic identity (T32.1-T32.5, T32.7)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.models.subject import Subject
from src.db.models.user import User
from src.db.repositories.topic_repo import TopicRepository
from src.ml.clustering.cross_session import (
    compute_updated_centroid,
    match_segment_to_topic,
    should_recluster,
)

pytestmark = pytest.mark.integration


async def _two_subjects(db: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    user = User(email=f"t-{uuid.uuid4().hex[:8]}@x.com", hashed_password="h", is_active=True)
    db.add(user)
    await db.flush()
    subject_a = Subject(user_id=user.id, name="Subject A")
    subject_b = Subject(user_id=user.id, name="Subject B")
    db.add_all([subject_a, subject_b])
    await db.flush()
    return subject_a.id, subject_b.id


class TestComputeUpdatedCentroid:
    def test_weighted_average(self) -> None:
        """T32.3: centroid_new = (centroid_old * count + new) / (count + 1)."""
        old = [1.0, 1.0]
        new = [3.0, 3.0]
        updated = compute_updated_centroid(old, new, old_count=1)
        assert updated == pytest.approx([2.0, 2.0])

    def test_first_update_from_count_zero(self) -> None:
        updated = compute_updated_centroid([0.0], [4.0], old_count=0)
        assert updated == pytest.approx([4.0])


class TestShouldRecluster:
    def test_cold_start_sessions(self) -> None:
        """S32 §6.2: sessions 2-5 recluster every 2 sessions."""
        assert should_recluster(2) is True
        assert should_recluster(3) is False
        assert should_recluster(4) is True
        assert should_recluster(5) is False

    def test_steady_state(self) -> None:
        assert should_recluster(10) is True
        assert should_recluster(11) is False
        assert should_recluster(20, recluster_interval=10) is True


class TestT32MatchingAndScoping:
    async def test_new_topic_when_no_existing_topics(self, db_session: AsyncSession) -> None:
        subject_a, _ = await _two_subjects(db_session)
        repo = TopicRepository(db_session)
        match = await match_segment_to_topic(subject_a, [1.0] * 1024, repo)
        assert match.is_new is True
        assert match.matched is False

    async def test_matches_similar_existing_topic(self, db_session: AsyncSession) -> None:
        """T32.1: a near-identical segment embedding links to the existing topic."""
        subject_a, _ = await _two_subjects(db_session)
        repo = TopicRepository(db_session)
        existing = await repo.create(subject_a, None, [1.0] * 1024)

        match = await match_segment_to_topic(subject_a, [0.999] * 1024, repo, threshold=0.9)
        assert match.matched is True
        assert match.topic_id == existing.id

    async def test_new_topic_for_dissimilar_embedding(self, db_session: AsyncSession) -> None:
        """T32.2: a genuinely different embedding does not force-match."""
        subject_a, _ = await _two_subjects(db_session)
        repo = TopicRepository(db_session)
        centroid = [1.0] + [0.0] * 1023
        await repo.create(subject_a, None, centroid)

        orthogonal = [0.0, 1.0] + [0.0] * 1022
        match = await match_segment_to_topic(subject_a, orthogonal, repo, threshold=0.75)
        assert match.matched is False
        assert match.is_new is True

    async def test_no_cross_subject_leakage(self, db_session: AsyncSession) -> None:
        """T32.5: matching for subject A never returns subject B's topics."""
        subject_a, subject_b = await _two_subjects(db_session)
        repo = TopicRepository(db_session)
        await repo.create(subject_b, None, [1.0] * 1024)

        match = await match_segment_to_topic(subject_a, [1.0] * 1024, repo, threshold=0.75)
        assert match.is_new is True
        assert match.topic_id is None
