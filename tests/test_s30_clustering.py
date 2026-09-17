"""Tests for S30 - topic clustering (T30.1, T30.3, T30.4, T30.5, T30.7)."""

from __future__ import annotations

import uuid

import numpy as np
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.models.session import Session, SessionStatus
from src.db.models.subject import Subject
from src.db.models.user import User
from src.db.partitions.provisioner import PartitionProvisioner
from src.db.repositories.segment_repo import SegmentRepository
from src.db.repositories.topic_repo import TopicRepository
from src.db.repositories.utterance_repo import UtteranceRepository
from src.ml.clustering.bertopic_pipeline import cluster_segment_embeddings, mean_pool_segment
from src.ml.clustering.segmentation import SegmentationResult, SegmentResult
from src.ml.clustering.tasks import cluster_segments

pytestmark = pytest.mark.integration


class TestMeanPoolSegment:
    def test_mean_pool(self) -> None:
        embeddings = [[1.0, 2.0, 3.0], [3.0, 2.0, 1.0]]
        pooled = mean_pool_segment(embeddings)
        assert pooled == pytest.approx([2.0, 2.0, 2.0])


class TestT303TwoDistinctTopics:
    def test_two_well_separated_clusters_yield_two_clusters(self) -> None:
        """T30.3: two synthetic topic blocks cluster into >= 2 clusters (FR-5.8)."""
        rng = np.random.default_rng(0)
        cluster_a = rng.normal(loc=0.0, scale=0.05, size=(15, 32)).tolist()
        cluster_b = rng.normal(loc=5.0, scale=0.05, size=(15, 32)).tolist()
        embeddings = cluster_a + cluster_b

        assignment = cluster_segment_embeddings(embeddings, min_cluster_size=5)

        non_noise_labels = {lbl for lbl in assignment.labels if lbl != -1}
        assert len(non_noise_labels) >= 2

    def test_single_segment_single_cluster(self) -> None:
        assignment = cluster_segment_embeddings([[1.0, 2.0, 3.0]])
        assert assignment.labels == [0]
        assert assignment.outlier_scores == [0.0]

    def test_zero_segments(self) -> None:
        assignment = cluster_segment_embeddings([])
        assert assignment.labels == []


class TestT303SmallNNeverProducesZeroTopics:
    """Confirmed live (docs/gaps.md #33e): a real 7-segment recording

    produced 0 topics because the fixed min_cluster_size=5 default was
    only ever validated against 30+-point test data. This is the
    previously-untested 2-9 segment regime.
    """

    def test_seven_scattered_embeddings_still_yield_a_topic(self) -> None:
        """Worst case for HDBSCAN: too few, too scattered points for the
        old fixed min_cluster_size=5 to ever find a real cluster in."""
        rng = np.random.default_rng(1)
        embeddings = rng.normal(loc=0.0, scale=1.0, size=(7, 32)).tolist()

        assignment = cluster_segment_embeddings(embeddings)

        assert len(assignment.centroids) >= 1
        assert all(lbl != -1 for lbl in assignment.labels)

    def test_three_embeddings_still_yield_a_topic(self) -> None:
        rng = np.random.default_rng(2)
        embeddings = rng.normal(loc=0.0, scale=1.0, size=(3, 16)).tolist()

        assignment = cluster_segment_embeddings(embeddings)

        assert len(assignment.centroids) >= 1
        assert all(lbl != -1 for lbl in assignment.labels)


async def _subject_session_with_utterances(
    db: AsyncSession, n: int
) -> tuple[uuid.UUID, uuid.UUID, list[uuid.UUID]]:
    user = User(email=f"t-{uuid.uuid4().hex[:8]}@x.com", hashed_password="h", is_active=True)
    db.add(user)
    await db.flush()
    provisioner = PartitionProvisioner()
    subject = await provisioner.provision_subject(
        db, user.id, name=f"S30 Subject {uuid.uuid4().hex[:8]}"
    )
    session_obj = Session(
        subject_id=subject.id, session_type="content", status=SessionStatus.PROCESSING
    )
    db.add(session_obj)
    await db.flush()

    utt_repo = UtteranceRepository(db)
    rows = [
        {
            "session_id": session_obj.id,
            "seq": i,
            "start_ms": i * 100,
            "end_ms": (i + 1) * 100,
            "text": f"utt {i}",
            "words": [],
            "asr_confidence": None,
            "speaker_tag": None,
            "embed_model_ver": "qwen3-0.6b-v1",
        }
        for i in range(n)
    ]
    await utt_repo.bulk_insert(subject.id, rows)

    result = await db.execute(
        text("SELECT id FROM utterances WHERE subject_id = :sid ORDER BY seq"),
        {"sid": str(subject.id)},
    )
    utt_ids = [uuid.UUID(str(r[0])) for r in result.fetchall()]

    for i, utt_id in enumerate(utt_ids):
        vec = [1.0] * 1024 if i < n // 2 else [-1.0] * 1024
        await utt_repo.update_embedding(subject.id, utt_id, vec, "qwen3-0.6b-v1")

    return subject.id, session_obj.id, utt_ids


class TestT301T305Integration:
    async def test_cluster_segments_persists_topics_and_outlier_scores(
        self, db_session: AsyncSession
    ) -> None:
        """T30.1/T30.5: clustering assigns topics (or outliers) and persists outlier_score."""
        n = 20
        subject_id, session_id, utt_ids = await _subject_session_with_utterances(db_session, n)

        seg_repo = SegmentRepository(db_session)
        segmentation = SegmentationResult(
            session_id=session_id,
            segments=[
                SegmentResult(utt_ids[0], utt_ids[9], 0, 9, 0.1, 0.9),
                SegmentResult(utt_ids[10], utt_ids[19], 10, 19, 0.1, 0.9),
            ],
            num_segments=2,
            similarity_scores=[],
        )
        await seg_repo.persist_segments(subject_id, session_id, segmentation)

        result = await cluster_segments.fn(
            session_id=session_id, subject_id=subject_id, db=db_session
        )

        assert result.session_id == session_id
        assert len(result.topic_assignments) == 2
        for assignment in result.topic_assignments:
            assert 0.0 <= assignment.outlier_score <= 1.0

        rows = await db_session.execute(
            text("SELECT outlier_score FROM utterances WHERE subject_id = :sid"),
            {"sid": str(subject_id)},
        )
        scores = [r[0] for r in rows.fetchall()]
        assert all(s is not None for s in scores)

    async def test_zero_segments_returns_empty_result(self, db_session: AsyncSession) -> None:
        subject_id, session_id, _ = await _subject_session_with_utterances(db_session, 5)
        result = await cluster_segments.fn(
            session_id=session_id, subject_id=subject_id, db=db_session
        )
        assert result.topics_created == 0
        assert result.segments_assigned == 0


class TestT304SubjectScoping:
    async def test_topics_scoped_to_subject(self, db_session: AsyncSession) -> None:
        """T30.4: topics created for subject A never leak into subject B's queries."""
        topic_repo = TopicRepository(db_session)
        user = User(email=f"t-{uuid.uuid4().hex[:8]}@x.com", hashed_password="h", is_active=True)
        db_session.add(user)
        await db_session.flush()
        subject_a = Subject(user_id=user.id, name="Subject A")
        subject_b = Subject(user_id=user.id, name="Subject B")
        db_session.add_all([subject_a, subject_b])
        await db_session.flush()

        await topic_repo.create(subject_a.id, None, [1.0] * 1024)
        await topic_repo.create(subject_b.id, None, [2.0] * 1024)

        topics_a = await topic_repo.list_for_subject(subject_a.id)
        topics_b = await topic_repo.list_for_subject(subject_b.id)

        assert len(topics_a) == 1
        assert len(topics_b) == 1
        assert topics_a[0].subject_id == subject_a.id
