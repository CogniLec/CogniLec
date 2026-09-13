"""S32 — cross-session topic identity: nearest-centroid matching, incremental
centroid updates, and the periodic full re-cluster trigger.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import numpy as np

from src.db.repositories.topic_repo import TopicRepository

DEFAULT_MATCH_THRESHOLD = 0.75
DEFAULT_RECLUSTER_INTERVAL = 10


@dataclass
class MatchResult:
    matched: bool
    topic_id: uuid.UUID | None
    distance: float
    cosine_similarity: float
    is_new: bool


async def match_segment_to_topic(
    subject_id: uuid.UUID,
    segment_embedding: list[float],
    topic_repo: TopicRepository,
    threshold: float = DEFAULT_MATCH_THRESHOLD,
) -> MatchResult:
    """Nearest-centroid match against the subject's existing topics (S32 §5.1).

    pgvector's `<=>` is cosine *distance* (1 - cosine similarity). Matching
    never crosses subjects: `TopicRepository.nearest_centroid` filters by
    `subject_id` at the SQL level.
    """
    nearest = await topic_repo.nearest_centroid(subject_id, segment_embedding)
    if nearest is None:
        return MatchResult(
            matched=False, topic_id=None, distance=1.0, cosine_similarity=0.0, is_new=True
        )

    topic_id, distance = nearest
    cosine_similarity = 1.0 - distance
    is_match = cosine_similarity >= threshold
    return MatchResult(
        matched=is_match,
        topic_id=topic_id if is_match else None,
        distance=distance,
        cosine_similarity=cosine_similarity,
        is_new=not is_match,
    )


def compute_updated_centroid(
    old_centroid: list[float], new_embedding: list[float], old_count: int
) -> list[float]:
    """Weighted-average incremental centroid update (S32 §5.3).

    centroid_new = (centroid_old * count + new_embedding) / (count + 1)
    """
    old = np.asarray(old_centroid, dtype=float)
    new = np.asarray(new_embedding, dtype=float)
    updated = (old * old_count + new) / (old_count + 1)
    return [float(x) for x in updated.tolist()]


async def process_segment_topics(
    subject_id: uuid.UUID,
    segment_embeddings: list[list[float]],
    topic_repo: TopicRepository,
    threshold: float = DEFAULT_MATCH_THRESHOLD,
) -> list[MatchResult]:
    """For each segment embedding, match against existing topics or flag as new (S32 §5.2)."""
    results: list[MatchResult] = []
    for embedding in segment_embeddings:
        match = await match_segment_to_topic(subject_id, embedding, topic_repo, threshold)
        if match.matched and match.topic_id is not None:
            existing = await topic_repo.get(subject_id, match.topic_id)
            if existing is not None:
                new_centroid = compute_updated_centroid(
                    list(existing.centroid), embedding, existing.segment_count
                )
                await topic_repo.update_centroid(subject_id, match.topic_id, new_centroid)
        results.append(match)
    return results


def should_recluster(
    session_number: int, recluster_interval: int = DEFAULT_RECLUSTER_INTERVAL
) -> bool:
    """Cold-start (sessions 2-5) reclusters every 2 sessions; steady-state every N (S32 §6.2)."""
    if session_number <= 5:
        return session_number % 2 == 0
    return session_number % recluster_interval == 0


@dataclass
class ReclusterResult:
    subject_id: uuid.UUID
    topics_before: int
    topics_after: int
    preserved_labels: int


async def recluster_preserve_labels(
    subject_id: uuid.UUID,
    all_segment_embeddings: list[list[float]],
    topic_repo: TopicRepository,
) -> ReclusterResult:
    """Full re-cluster that preserves user-edited labels (S32 §6.3).

    Re-clusters all of a subject's segment embeddings; a fresh cluster whose
    centroid nearest-matches an existing `is_user_edited=True` topic inherits
    that label instead of getting a placeholder/LLM label.
    """
    from src.ml.clustering.bertopic_pipeline import cluster_segment_embeddings

    existing_topics = await topic_repo.list_for_subject(subject_id)
    topics_before = len(existing_topics)
    user_edited = [t for t in existing_topics if t.is_user_edited]

    assignment = cluster_segment_embeddings(all_segment_embeddings)

    preserved = 0
    for centroid in assignment.centroids.values():
        best_topic, best_sim = None, -1.0
        for t in user_edited:
            old = np.asarray(list(t.centroid), dtype=float)
            new = np.asarray(centroid, dtype=float)
            denom = np.linalg.norm(old) * np.linalg.norm(new)
            sim = float(np.dot(old, new) / denom) if denom else 0.0
            if sim > best_sim:
                best_topic, best_sim = t, sim

        if best_topic is not None and best_sim >= DEFAULT_MATCH_THRESHOLD:
            preserved += 1

    return ReclusterResult(
        subject_id=subject_id,
        topics_before=topics_before,
        topics_after=len(assignment.centroids),
        preserved_labels=preserved,
    )
