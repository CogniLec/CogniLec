"""S53 — re-cluster cadence and seeded KMeans clustering."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import numpy as np
from sklearn.cluster import KMeans
from src.services.clustering.seed import (
    SEED_REPLACEMENT_THRESHOLD,
    TIGHT_CADENCE_SESSIONS,
    CentroidSeed,
    CentroidSeedService,
    cosine_similarity,
)

NORMAL_CADENCE_INTERVAL = 5
MIN_TOPICS_FOR_RECLUSTER = 3


@dataclass
class ClusterResult:
    cluster_id: int
    centroid: list[float]
    member_indices: list[int]


class ReclusterService:
    def __init__(self, seed_service: CentroidSeedService) -> None:
        self._seed_service = seed_service

    async def should_recluster(self, subject_id: uuid.UUID, session_number: int) -> bool:
        """Session 1: no re-cluster. Sessions 2-5: always. Session 6+: every N."""
        if session_number <= 1:
            return False
        if session_number <= TIGHT_CADENCE_SESSIONS:
            return True
        return (session_number - TIGHT_CADENCE_SESSIONS) % NORMAL_CADENCE_INTERVAL == 0

    async def recluster(
        self, subject_id: uuid.UUID, topic_embeddings: list[list[float]]
    ) -> list[ClusterResult]:
        """Re-cluster topic embeddings, seeded with active syllabus centroids."""
        if len(topic_embeddings) < MIN_TOPICS_FOR_RECLUSTER:
            return []

        seeds = await self._seed_service.get_seeds(subject_id)
        active_seeds = [s for s in seeds if not s.replaced_by_data]
        data = np.asarray(topic_embeddings)

        if active_seeds:
            n_clusters = min(len(active_seeds), len(topic_embeddings))
            init = np.asarray([s.embedding for s in active_seeds[:n_clusters]])
            model = KMeans(n_clusters=n_clusters, init=init, n_init=1, random_state=0)
        else:
            n_clusters = min(max(len(topic_embeddings) // 3, 1), len(topic_embeddings))
            model = KMeans(n_clusters=n_clusters, n_init=10, random_state=0)

        labels = model.fit_predict(data)
        results = []
        for cluster_id in range(n_clusters):
            member_indices = [i for i, label in enumerate(labels) if label == cluster_id]
            if not member_indices:
                continue
            results.append(
                ClusterResult(
                    cluster_id=cluster_id,
                    centroid=model.cluster_centers_[cluster_id].tolist(),
                    member_indices=member_indices,
                )
            )

        await self.replace_seeds_from_clusters(subject_id, results, active_seeds)
        return results

    async def replace_seeds_from_clusters(
        self,
        subject_id: uuid.UUID,
        clusters: list[ClusterResult],
        active_seeds: list[CentroidSeed] | None = None,
    ) -> int:
        """Replace seed centroids whose nearest real cluster center exceeds the threshold."""
        seeds = (
            active_seeds
            if active_seeds is not None
            else await self._seed_service.get_seeds(subject_id)
        )
        replaced = 0
        for seed in seeds:
            if seed.replaced_by_data:
                continue
            best = max(
                (cosine_similarity(seed.embedding, c.centroid) for c in clusters),
                default=0.0,
            )
            if best > SEED_REPLACEMENT_THRESHOLD:
                await self._seed_service.replace_seed(
                    subject_id, seed.syllabus_item_id, seed.embedding
                )
                replaced += 1
        return replaced


__all__ = [
    "MIN_TOPICS_FOR_RECLUSTER",
    "NORMAL_CADENCE_INTERVAL",
    "ClusterResult",
    "ReclusterService",
]
