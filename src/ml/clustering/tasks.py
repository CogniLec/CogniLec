"""S30 — Prefect task T3: cluster segment embeddings into topics."""

from __future__ import annotations

import uuid
from datetime import timedelta

from prefect import task
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.repositories.segment_repo import SegmentRepository
from src.db.repositories.topic_repo import TopicRepository
from src.ml.clustering.bertopic_pipeline import cluster_segment_embeddings, mean_pool_segment
from src.ml.clustering.schemas import ClusteringResult, SegmentTopicAssignment


def _cache_key_t3(context: object, parameters: dict[str, object]) -> str:
    return f"T3-{parameters['session_id']}"


async def _segment_member_embeddings(
    db: AsyncSession, subject_id: uuid.UUID, start_utt: uuid.UUID, end_utt: uuid.UUID
) -> tuple[list[uuid.UUID], list[list[float]]]:
    """Utterances between a segment's start/end (inclusive) ordered by seq."""
    result = await db.execute(
        text("""
            SELECT id, embedding FROM utterances
            WHERE subject_id = :subject_id AND session_id = (
                SELECT session_id FROM utterances WHERE id = :start_utt
            )
            AND seq BETWEEN
                (SELECT seq FROM utterances WHERE id = :start_utt)
                AND (SELECT seq FROM utterances WHERE id = :end_utt)
            ORDER BY seq
        """),
        {"subject_id": str(subject_id), "start_utt": str(start_utt), "end_utt": str(end_utt)},
    )
    rows = result.mappings().all()
    ids = [uuid.UUID(str(r["id"])) for r in rows]
    embeddings = [_parse_vector(r["embedding"]) for r in rows if r["embedding"] is not None]
    return ids, embeddings


def _parse_vector(value: str | list[float]) -> list[float]:
    """asyncpg returns pgvector columns as their `[1,2,3]` text literal via raw SQL."""
    if isinstance(value, str):
        return [float(x) for x in value.strip("[]").split(",")]
    return [float(x) for x in value]


@task(
    name="T3_cluster_segments",
    cache_key_fn=_cache_key_t3,
    cache_expiration=timedelta(hours=24),
    retries=1,
    retry_delay_seconds=60,
)
async def cluster_segments(
    session_id: uuid.UUID,
    subject_id: uuid.UUID,
    db: AsyncSession,
) -> ClusteringResult:
    """T3: mean-pool each segment's member embeddings, cluster with BERTopic.

    Persists topics with centroids, updates each segment's topic_id, and
    stores the HDBSCAN outlier score on every member utterance (S30 §6.4).
    """
    segment_repo = SegmentRepository(db)
    topic_repo = TopicRepository(db)

    segments = await segment_repo.get_by_session(subject_id, session_id)
    if not segments:
        return ClusteringResult(
            session_id=session_id,
            topics_created=0,
            segments_assigned=0,
            outliers=0,
            topic_assignments=[],
        )

    segment_embeddings: list[list[float]] = []
    member_ids_per_segment: list[list[uuid.UUID]] = []
    for seg in segments:
        member_ids, embeddings = await _segment_member_embeddings(
            db, subject_id, seg.start_utt, seg.end_utt
        )
        member_ids_per_segment.append(member_ids)
        segment_embeddings.append(mean_pool_segment(embeddings) if embeddings else [0.0] * 1024)

    assignment = cluster_segment_embeddings(segment_embeddings)

    topic_ids_by_label: dict[int, uuid.UUID] = {}
    for lbl, centroid in assignment.centroids.items():
        topic = await topic_repo.create(
            subject_id=subject_id, session_id=session_id, centroid=centroid
        )
        topic_ids_by_label[lbl] = topic.id

    outliers = 0
    result_assignments: list[SegmentTopicAssignment] = []
    for seg, lbl, outlier_score, member_ids in zip(
        segments, assignment.labels, assignment.outlier_scores, member_ids_per_segment, strict=True
    ):
        is_outlier = lbl == -1
        topic_id = None if is_outlier else topic_ids_by_label.get(lbl)
        if is_outlier:
            outliers += 1

        await db.execute(
            text(
                "UPDATE segments SET topic_id = :topic_id "
                "WHERE subject_id = :subject_id AND id = :id"
            ),
            {
                "topic_id": str(topic_id) if topic_id else None,
                "subject_id": str(subject_id),
                "id": str(seg.id),
            },
        )
        for utt_id in member_ids:
            await db.execute(
                text(
                    "UPDATE utterances SET outlier_score = :score, topic_id = :topic_id "
                    "WHERE subject_id = :subject_id AND id = :id"
                ),
                {
                    "score": outlier_score,
                    "topic_id": str(topic_id) if topic_id else None,
                    "subject_id": str(subject_id),
                    "id": str(utt_id),
                },
            )

        result_assignments.append(
            SegmentTopicAssignment(
                segment_id=seg.id,
                topic_id=topic_id,
                outlier_score=outlier_score,
                is_outlier=is_outlier,
            )
        )

    await db.flush()

    return ClusteringResult(
        session_id=session_id,
        topics_created=len(topic_ids_by_label),
        segments_assigned=len(segments) - outliers,
        outliers=outliers,
        topic_assignments=result_assignments,
    )
