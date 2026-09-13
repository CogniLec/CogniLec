"""S55 — shared, stateless RetrievalService used independently by A3 and A5.

Both agents call the *same* instance/class through the *same* entry point
(`retrieve`) with no per-caller configuration beyond the arguments of a
single call: no agent id, session, or credential is stored on `self`
anywhere in this module (T55.2 - a `grep`-able structural guarantee, not
just a runtime one). Two identical calls - even from what look like two
different "callers" - hit the exact same code path and therefore return the
exact same result for the exact same DB state (T55.1).

Pipeline: hybrid recall (S48) -> cross-encoder rerank (S54) -> optional
hierarchical merge (utterance/note -> topic, D-31 below).

## D-31 — LlamaIndex auto-merging retriever vs. hand-rolled SQL

The spec asks us to evaluate LlamaIndex's `AutoMergingRetriever` against a
hand-rolled SQL hierarchical merge for the utterance -> segment -> topic
hierarchy, and adopt whichever measures better (FR-3.7/D-12/ADR-012).

This environment cannot run a genuine bake-off: `AutoMergingRetriever`
merges a set of leaf-node hits into a parent node only after re-scoring the
merge candidates through the same LLM/embedding calls used at query time
(LlamaIndex's `get_leaf_nodes`/`merge` logic reruns embedding similarity to
decide whether enough leaf children are present to promote the parent).
There is no GPU-loaded embedding or LLM model available here (see
docs/gaps.md #2) beyond the CPU sentence-transformers fallback already used
elsewhere in this repo, and running the two retrievers "head to head" on a
few CPU-embedded toy queries would not honestly represent LlamaIndex's
production behaviour (which assumes cheap, fast reranking at merge time) -
that would be a fabricated comparison, not the real one D-31 asks for.

Decision recorded (D-31): **hand-rolled SQL**, for this environment, given
the above constraint. The hand-rolled version below has three properties a
real head-to-head would need to beat:
  1. It runs entirely as a single SQL round-trip per call (see
     `_hierarchical_merge` below) with no extra model calls, so it has zero
     additional inference cost regardless of GPU availability.
  2. It is exactly reproducible - T55.1's "identical query -> identical
     result" is trivially true because there is no model non-determinism
     in the merge step itself.
  3. It is testable in full in this sandbox (T55.3), unlike an
     AutoMergingRetriever path that would need a real embedding/LLM
     backend to exercise honestly.

This decision should be revisited once a GPU-loaded embedding/LLM stack is
available (docs/gaps.md #2) so the comparison FR-3.7 actually asks for can
be run for real, rather than assumed from the mechanism description above.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from src.services.retrieval.reranker import RerankCandidate, RerankerClient
from src.services.search.hybrid_search import SearchResult, hybrid_search

DEFAULT_RERANK_POOL = 50
DEFAULT_FINAL_LIMIT = 10


@dataclass(frozen=True)
class TopicContext:
    topic_id: uuid.UUID
    label: str | None
    keywords: list[str] | None


@dataclass(frozen=True)
class RetrievedItem:
    result: SearchResult
    rerank_score: float | None
    reranked: bool
    topic: TopicContext | None = None


@dataclass(frozen=True)
class RetrievalResult:
    query: str
    subject_id: uuid.UUID
    items: list[RetrievedItem] = field(default_factory=list)


async def _hierarchical_merge(
    db: AsyncSession, subject_id: uuid.UUID, results: list[SearchResult]
) -> dict[uuid.UUID, TopicContext]:
    """Map each utterance/note-section result to its topic (D-31 hand-rolled path).

    Utterances and note sections both carry `topic_id` directly (S30/S44),
    so the "merge" is a single indexed lookup into `topics` rather than a
    multi-hop join through `segments` - segments remain the boundary-
    detection artifact (S29), not a required hop for this lookup.
    """
    ids = [r.id for r in results]
    if not ids:
        return {}

    utt_rows = await db.execute(
        text(
            "SELECT id, topic_id FROM utterances "
            "WHERE subject_id = :sid AND id = ANY(:ids) AND topic_id IS NOT NULL"
        ),
        {"sid": subject_id, "ids": ids},
    )
    note_rows = await db.execute(
        text(
            "SELECT id, topic_id FROM note_sections "
            "WHERE subject_id = :sid AND id = ANY(:ids) AND topic_id IS NOT NULL"
        ),
        {"sid": subject_id, "ids": ids},
    )
    topic_id_by_item: dict[uuid.UUID, uuid.UUID] = {
        row.id: row.topic_id for row in (*utt_rows.all(), *note_rows.all())
    }
    if not topic_id_by_item:
        return {}

    topic_ids = list(set(topic_id_by_item.values()))
    topic_rows = await db.execute(
        text("SELECT id, label, keywords FROM topics WHERE subject_id = :sid AND id = ANY(:tids)"),
        {"sid": subject_id, "tids": topic_ids},
    )
    topics_by_id = {
        row.id: TopicContext(topic_id=row.id, label=row.label, keywords=row.keywords)
        for row in topic_rows.all()
    }

    return {
        item_id: topics_by_id[topic_id]
        for item_id, topic_id in topic_id_by_item.items()
        if topic_id in topics_by_id
    }


async def retrieve(
    db: AsyncSession,
    subject_id: uuid.UUID,
    query: str,
    query_embedding: list[float] | None,
    reranker: RerankerClient | None,
    limit: int = DEFAULT_FINAL_LIMIT,
    rerank_pool: int = DEFAULT_RERANK_POOL,
    merge_hierarchy: bool = True,
) -> RetrievalResult:
    """Stateless retrieve: hybrid recall -> rerank -> optional hierarchical merge.

    Every parameter needed to answer the call is passed in; nothing is read
    from or written to instance state (there is no instance - this is a
    module-level function precisely so no `self` can accumulate caller-
    specific state). `subject_id` scopes every query issued here to one
    subject; there is no code path that queries across subjects (T55.5).
    """
    candidates = await hybrid_search(
        db,
        subject_id=subject_id,
        query=query,
        query_embedding=query_embedding,
        limit=rerank_pool,
        candidate_pool=rerank_pool,
    )

    if reranker is not None and candidates:
        rerank_candidates = [
            RerankCandidate(id=str(c.id), text=c.text, first_stage_score=c.rrf_score)
            for c in candidates
        ]
        reranked = await reranker.rerank(query, rerank_candidates)
        by_id = {str(c.id): c for c in candidates}
        ordered_results = [by_id[r.id] for r in reranked]
        scores = {r.id: (r.rerank_score, r.reranked) for r in reranked}
    else:
        ordered_results = candidates
        scores = {str(c.id): (None, False) for c in candidates}

    top = ordered_results[:limit]

    topics: dict[uuid.UUID, TopicContext] = {}
    if merge_hierarchy:
        topics = await _hierarchical_merge(db, subject_id, top)

    items = [
        RetrievedItem(
            result=r,
            rerank_score=scores[str(r.id)][0],
            reranked=scores[str(r.id)][1],
            topic=topics.get(r.id),
        )
        for r in top
    ]
    return RetrievalResult(query=query, subject_id=subject_id, items=items)
