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
from src.ml.clustering.keywords import extract_keywords
from src.ml.clustering.labelling import generate_topic_label
from src.ml.clustering.schemas import ClusteringResult, SegmentTopicAssignment
from src.services.llm.router import LLMRouter


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


class _RouterLabellingClient:
    """Adapts `LLMRouter.complete(messages, ...)` to `generate_topic_label`'s
    duck-typed `complete(prompt: str) -> str` Protocol."""

    def __init__(self, router: LLMRouter, prompt_version: str) -> None:
        self._router = router
        self._prompt_version = prompt_version

    async def complete(self, prompt: str) -> str:
        response = await self._router.complete(
            [{"role": "user", "content": prompt}],
            agent_id="A_TOPIC_LABEL",
            prompt_version=self._prompt_version,
        )
        return "" if response.failed else response.content


def _cache_key_t3b(context: object, parameters: dict[str, object]) -> str:
    return f"T3b-{parameters['session_id']}"


@task(
    name="T3b_label_topics",
    cache_key_fn=_cache_key_t3b,
    cache_expiration=timedelta(hours=24),
    retries=1,
    retry_delay_seconds=30,
)
async def label_topics(
    session_id: uuid.UUID,
    subject_id: uuid.UUID,
    db: AsyncSession,
    router: LLMRouter | None,
    prompt_version: str,
    n_representative: int = 10,
) -> int:
    """T3b (S31): generate real labels + keywords for topics T3 just created.

    T3 (`cluster_segments` above) only ever wrote `centroid` when creating
    Topic rows -- `label`/`keywords` were left NULL. `generate_topic_label`
    (S31, `src.ml.clustering.labelling`) and `extract_keywords`
    (`src.ml.clustering.keywords`) already existed, fully implemented and
    tested, but were never called from the running pipeline -- confirmed
    live: a real session produced topics with an empty `label`, which fed a
    meaningless "unlabeled topic" string into flashcard retrieval and
    produced hallucinated, ungrounded flashcards (docs/gaps.md #33a
    follow-up). This wires the existing labeller in, right after T3.

    `router=None` (no LLM available) degrades gracefully to leaving topics
    unlabeled, same as before this task existed -- matches
    `generate_topic_label`'s own "never break the pipeline" contract and
    `process_session`'s existing optional-dependency pattern (`ensemble`,
    `stream`).
    """
    if router is None:
        return 0

    topic_repo = TopicRepository(db)
    result = await db.execute(
        text(
            "SELECT DISTINCT topic_id FROM segments "
            "WHERE subject_id = :subject_id AND session_id = :session_id "
            "AND topic_id IS NOT NULL"
        ),
        {"subject_id": str(subject_id), "session_id": str(session_id)},
    )
    topic_ids = [uuid.UUID(str(r[0])) for r in result.all()]

    labelling_client = _RouterLabellingClient(router, prompt_version)
    labelled = 0
    for topic_id in topic_ids:
        topic = await topic_repo.get(subject_id, topic_id)
        if topic is None or topic.label:
            continue

        utt_result = await db.execute(
            text(
                "SELECT text FROM utterances "
                "WHERE subject_id = :subject_id AND topic_id = :topic_id "
                "ORDER BY seq LIMIT :n"
            ),
            {"subject_id": str(subject_id), "topic_id": str(topic_id), "n": n_representative},
        )
        texts = [str(r[0]) for r in utt_result.all()]
        if not texts:
            continue

        keyword_results = extract_keywords(texts)
        keywords = [k.keyword for k in keyword_results]
        scores = [k.score for k in keyword_results]

        label = await generate_topic_label(topic_id, texts, keywords, labelling_client)
        await topic_repo.update_label(subject_id, topic_id, label, is_user_edited=False)
        if keywords:
            await topic_repo.update_keywords(subject_id, topic_id, keywords, scores)
        labelled += 1

    return labelled
