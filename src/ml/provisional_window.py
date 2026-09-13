"""S33 — Provisional 10-minute topic window pass.

A lightweight preview of the S30 BERTopic pipeline over the first N minutes
of a session, surfaced to the client for an early "does this look like the
right subject?" check. Never authoritative — the post-session full-transcript
pass (S30) always wins (FR-2.9).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Protocol

from pydantic import BaseModel

from src.ml.clustering.bertopic_pipeline import cluster_segment_embeddings

log = logging.getLogger(__name__)

DEFAULT_WINDOW_MINUTES = 10
DEFAULT_MIN_UTTERANCES = 5


class ProvisionalTopic(BaseModel):
    label: str | None = None
    keywords: list[str] = []
    centroid: list[float]
    utterance_count: int
    start_seq: int
    end_seq: int


class ProvisionalWindowResult(BaseModel):
    session_id: uuid.UUID
    window_minutes: int
    topics: list[ProvisionalTopic]
    utterances_in_window: int
    generated_at: datetime
    is_authoritative: bool = False


class EmbeddedUtteranceLike(Protocol):
    seq: int
    start_ms: int
    embedding: list[float]


def select_window_utterances(
    utterances: Sequence[EmbeddedUtteranceLike],
    window_minutes: int = DEFAULT_WINDOW_MINUTES,
) -> list[EmbeddedUtteranceLike]:
    """Select utterances within the first `window_minutes` of the session."""
    if not utterances:
        return []
    window_ms = window_minutes * 60_000
    session_start_ms = utterances[0].start_ms
    return [u for u in utterances if u.start_ms - session_start_ms < window_ms]


def run_provisional_window(
    session_id: uuid.UUID,
    utterances: Sequence[EmbeddedUtteranceLike],
    window_minutes: int = DEFAULT_WINDOW_MINUTES,
    min_cluster_size: int | None = None,
    min_utterances: int = DEFAULT_MIN_UTTERANCES,
) -> ProvisionalWindowResult | None:
    """Run the provisional clustering pass. Returns None if skipped (< min_utterances).

    Failure handling per spec §6.2: < min_utterances -> skip, log warning, no
    exception. Clustering with 0 topics still returns a result (topic_count=0).
    """
    window = select_window_utterances(utterances, window_minutes)

    if len(window) < min_utterances:
        log.warning(
            "provisional_window_skipped",
            extra={"session_id": str(session_id), "utterance_count": len(window)},
        )
        return None

    embeddings = [u.embedding for u in window]
    assignment = cluster_segment_embeddings(embeddings, min_cluster_size=min_cluster_size)

    topics: list[ProvisionalTopic] = []
    for label, centroid in assignment.centroids.items():
        member_seqs = [window[i].seq for i, lbl in enumerate(assignment.labels) if lbl == label]
        if not member_seqs:
            continue
        topics.append(
            ProvisionalTopic(
                centroid=centroid,
                utterance_count=len(member_seqs),
                start_seq=min(member_seqs),
                end_seq=max(member_seqs),
            )
        )

    if not topics:
        log.info("provisional_clustering_empty", extra={"session_id": str(session_id)})

    return ProvisionalWindowResult(
        session_id=session_id,
        window_minutes=window_minutes,
        topics=topics,
        utterances_in_window=len(window),
        generated_at=datetime.now(UTC),
        is_authoritative=False,
    )
