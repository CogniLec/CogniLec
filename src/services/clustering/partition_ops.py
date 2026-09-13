"""S75 — operator tooling for topic partition merge/split with audit logging.

FR-5.13's merge/split operations reuse the existing `topics` table (S30) as
the thing being merged or split; this module is the audit-logged wrapper
around plain topic-row updates, not a new clustering algorithm. Every
merge/split writes one `partition_operations` row capturing the full
before/after topic state (including the pgvector `centroid`, cast to a
plain list so it round-trips through JSONB), and `reverse_merge` replays
that row's `before_state` to undo a merge (T75.5) without re-clustering.

`topics`' primary key is composite (`subject_id`, `id`) (S30), so every
lookup here filters on both.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def _topic_state(
    db_session: AsyncSession, subject_id: uuid.UUID, topic_ids: list[uuid.UUID]
) -> list[dict[str, Any]]:
    rows = (
        await db_session.execute(
            text(
                "SELECT id, subject_id, label, centroid::text AS centroid "
                "FROM topics WHERE subject_id = :sid AND id = ANY(:ids)"
            ),
            {"sid": str(subject_id), "ids": topic_ids},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def merge_topics(
    db_session: AsyncSession,
    subject_id: uuid.UUID,
    topic_ids: list[uuid.UUID],
    merged_label: str,
    performed_by: uuid.UUID | None = None,
) -> uuid.UUID:
    """Merge `topic_ids` into one topic labelled `merged_label`; segments repointed to it."""
    if len(topic_ids) < 2:
        msg = "merge requires at least two topics"
        raise ValueError(msg)

    before_state = {"topics": await _topic_state(db_session, subject_id, topic_ids)}
    survivor_id = topic_ids[0]
    absorbed_ids = topic_ids[1:]

    await db_session.execute(
        text("UPDATE topics SET label = :label WHERE subject_id = :sid AND id = :id"),
        {"label": merged_label, "sid": str(subject_id), "id": str(survivor_id)},
    )
    for absorbed_id in absorbed_ids:
        await db_session.execute(
            text(
                "UPDATE segments SET topic_id = :survivor "
                "WHERE topic_id = :absorbed"
            ),
            {"survivor": str(survivor_id), "absorbed": str(absorbed_id)},
        )
        await db_session.execute(
            text("DELETE FROM topics WHERE subject_id = :sid AND id = :id"),
            {"sid": str(subject_id), "id": str(absorbed_id)},
        )

    after_state = {"topics": await _topic_state(db_session, subject_id, [survivor_id])}

    op_id = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO partition_operations "
            "(id, subject_id, operation_type, before_state, after_state, performed_by) "
            "VALUES (:id, :sid, 'merge', CAST(:before AS JSONB), CAST(:after AS JSONB), :by)"
        ),
        {
            "id": str(op_id),
            "sid": str(subject_id),
            "before": json.dumps(before_state, default=str),
            "after": json.dumps(after_state, default=str),
            "by": str(performed_by) if performed_by else None,
        },
    )
    await db_session.flush()
    return op_id


async def reverse_merge(db_session: AsyncSession, operation_id: uuid.UUID) -> None:
    """Recreate the pre-merge topics recorded in `operation_id`'s `before_state`."""
    row = (
        await db_session.execute(
            text(
                "SELECT subject_id, operation_type, before_state, reverted_at "
                "FROM partition_operations WHERE id = :id"
            ),
            {"id": str(operation_id)},
        )
    ).mappings().first()
    if row is None:
        msg = f"no such operation: {operation_id}"
        raise ValueError(msg)
    if row["operation_type"] != "merge":
        msg = "only merge operations can be reversed"
        raise ValueError(msg)
    if row["reverted_at"] is not None:
        msg = "operation already reverted"
        raise ValueError(msg)

    subject_id = row["subject_id"]
    before_topics = row["before_state"]["topics"]
    survivor = before_topics[0]
    await db_session.execute(
        text("UPDATE topics SET label = :label WHERE subject_id = :sid AND id = :id"),
        {"label": survivor["label"], "sid": str(subject_id), "id": survivor["id"]},
    )
    for topic in before_topics[1:]:
        await db_session.execute(
            text(
                "INSERT INTO topics (id, subject_id, label, centroid) "
                "VALUES (:id, :sid, :label, CAST(:centroid AS vector))"
            ),
            {
                "id": topic["id"],
                "sid": str(subject_id),
                "label": topic["label"],
                "centroid": topic["centroid"],
            },
        )

    await db_session.execute(
        text("UPDATE partition_operations SET reverted_at = now() WHERE id = :id"),
        {"id": str(operation_id)},
    )
    await db_session.flush()
