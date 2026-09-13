"""S25 §6.5 — resumable per-subject embedding backfill.

Progress is tracked in Valkey (`backfill:{subject_id}:{from_version}:{to_version}`)
so a crashed backfill resumes from the last completed batch instead of restarting.
"""

from __future__ import annotations

import uuid

from redis.asyncio import Redis

from src.db.repositories.utterance_repo import UtteranceRepository
from src.ml.embedding.client import EmbeddingClient
from src.ml.embedding.schemas import BackfillResult


def _progress_key(subject_id: uuid.UUID, from_version: str, to_version: str) -> str:
    return f"backfill:{subject_id}:{from_version}:{to_version}"


async def backfill_version(
    subject_id: uuid.UUID,
    from_version: str,
    to_version: str,
    repo: UtteranceRepository,
    client: EmbeddingClient,
    redis: Redis | None = None,
    batch_size: int = 100,
) -> BackfillResult:
    """Resumable backfill: re-embed all of a subject's utterances at `from_version`.

    Process (S25 §6.5): query rows at `from_version`, batch-embed at
    `to_version`, update embedding + embed_model_ver per batch, and record
    progress in Valkey so a crash resumes from the last completed batch
    rather than re-embedding from scratch.
    """
    rows = await repo.get_by_embed_version(subject_id, from_version)
    total = len(rows)

    resumed_from = 0
    key = _progress_key(subject_id, from_version, to_version)
    if redis is not None:
        stored = await redis.get(key)
        if stored is not None:
            resumed_from = int(stored)

    updated = resumed_from
    for start in range(resumed_from, total, batch_size):
        batch = rows[start : start + batch_size]
        texts = [str(row["text"]) for row in batch]
        vectors = await client.embed(texts, task_mode="clustering")

        for row, vector in zip(batch, vectors, strict=True):
            await repo.update_embedding(subject_id, uuid.UUID(str(row["id"])), vector, to_version)

        updated = start + len(batch)
        if redis is not None:
            await redis.set(key, updated)

    if redis is not None:
        await redis.delete(key)

    return BackfillResult(
        subject_id=str(subject_id),
        from_version=from_version,
        to_version=to_version,
        total=total,
        updated=updated,
        resumed_from=resumed_from,
    )
