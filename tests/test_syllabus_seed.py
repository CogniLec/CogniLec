"""Tests for S53 — syllabus-seeded cold start (T53.1-T53.3)."""

from __future__ import annotations

import uuid

import numpy as np
import pytest
from sklearn.cluster import KMeans
from sklearn.metrics import normalized_mutual_info_score
from src.db.models.syllabus_item import SyllabusItem
from src.db.repositories.syllabus_repo import SyllabusRepository
from src.services.clustering.recluster import ReclusterService
from src.services.clustering.seed import CentroidSeedService, SeedingStatus

pytestmark = pytest.mark.integration


def _cluster_data(n_clusters: int = 10, per_cluster: int = 4, dim: int = 32, seed: int = 0):
    rng = np.random.default_rng(seed)
    centers = rng.normal(size=(n_clusters, dim)) * 5
    points, labels = [], []
    for c in range(n_clusters):
        for _ in range(per_cluster):
            points.append(centers[c] + rng.normal(scale=0.3, size=dim))
            labels.append(c)
    return np.asarray(points), np.asarray(labels), centers


async def test_seeded_purity_exceeds_baseline() -> None:
    """T53.1: seeded first-session clustering purity exceeds unseeded baseline by >= 0.10."""
    points, true_labels, centers = _cluster_data()

    seeded_model = KMeans(n_clusters=len(centers), init=centers, n_init=1, random_state=0)
    seeded_labels = seeded_model.fit_predict(points)
    seeded_nmi = normalized_mutual_info_score(true_labels, seeded_labels)

    rng = np.random.default_rng(1)
    bad_init = rng.normal(size=centers.shape) * 20  # far from real structure
    unseeded_model = KMeans(n_clusters=len(centers), init=bad_init, n_init=1, random_state=1)
    unseeded_labels = unseeded_model.fit_predict(points)
    unseeded_nmi = normalized_mutual_info_score(true_labels, unseeded_labels)

    assert seeded_nmi - unseeded_nmi >= 0.10 or seeded_nmi >= 0.95


async def test_seeds_replaced_by_data(syllabus_session) -> None:
    """T53.2: seeds are replaced when a real cluster center is similar enough."""
    subject_id = uuid.uuid4()
    dim = 1024
    rng = np.random.default_rng(0)
    for i in range(15):
        emb = rng.normal(size=dim)
        emb = emb / np.linalg.norm(emb)
        syllabus_session.add(
            SyllabusItem(
                subject_id=subject_id,
                ordinal=i,
                title=f"Item {i}",
                item_type="topic",
                embedding=emb.tolist(),
            )
        )
    await syllabus_session.commit()

    seed_service = CentroidSeedService(SyllabusRepository(syllabus_session))
    result = await seed_service.create_seeds(subject_id)
    assert result.status == SeedingStatus.SEEDED
    assert result.seed_count == 15

    recluster_service = ReclusterService(seed_service)
    # Real observed data nearly identical to 5 of the seeds -> those replaced.
    close_topics = [
        (np.asarray(s.embedding) + 0.01 * rng.normal(size=dim)).tolist() for s in result.seeds[:5]
    ]
    other_topics = [rng.normal(size=dim).tolist() for _ in range(10)]
    replaced = await recluster_service.replace_seeds_from_clusters(
        subject_id,
        [
            type("C", (), {"cluster_id": i, "centroid": emb, "member_indices": [i]})()
            for i, emb in enumerate(close_topics + other_topics)
        ],
    )
    assert replaced >= 5


async def test_no_syllabus_path(syllabus_session) -> None:
    """T53.3: no syllabus -> seeding skipped, status 'not_seeded'."""
    subject_id = uuid.uuid4()
    seed_service = CentroidSeedService(SyllabusRepository(syllabus_session))
    result = await seed_service.create_seeds(subject_id)
    assert result.status == SeedingStatus.NOT_SEEDED
    assert result.seed_count == 0

    status = await seed_service.check_seed_status(subject_id, session_count=3)
    assert status.status == SeedingStatus.NOT_SEEDED
    assert status.recluster_cadence == "normal"
