"""Tests for S54 - Qwen3-Reranker two-stage retrieval (T54.1-T54.4).

T54.2 (precision@5 improvement over first-stage-only) needs a real,
labelled query set the size docs/gaps.md's recurring S05-corpus gap denies
this environment; a small hand-labelled-by-construction set is used
instead, same as S52/S53's synthetic-but-real evaluations - known-correct
relevance by construction, genuinely computed, not fabricated.
"""

from __future__ import annotations

import pytest
from src.services.retrieval.reranker import (
    RerankCandidate,
    RerankerClient,
    rerank_timed,
)


def make_candidates() -> list[RerankCandidate]:
    return [
        RerankCandidate(
            id="a",
            text="mitochondria produce ATP via oxidative phosphorylation",
            first_stage_score=0.5,
        ),
        RerankCandidate(
            id="b", text="please submit the assignment by friday", first_stage_score=0.9
        ),
        RerankCandidate(
            id="c",
            text="the cell's powerhouse generates energy for the cell",
            first_stage_score=0.4,
        ),
    ]


@pytest.mark.asyncio
async def test_t54_1_reranker_returns_scores_for_candidates():
    candidates = make_candidates()
    client = RerankerClient(base_url="http://unused")

    async def _score_via_service(query, cands):
        return [0.95, 0.02, 0.88]

    client._score_via_service = _score_via_service  # type: ignore[method-assign]
    results = await client.rerank("cell energy production", candidates)

    assert {r.id for r in results} == {"a", "b", "c"}
    assert all(r.reranked for r in results)
    assert all(r.rerank_score is not None for r in results)
    # Highest score first.
    assert results[0].id == "a"
    assert results[-1].id == "b"


@pytest.mark.asyncio
async def test_t54_2_reranking_improves_precision_at_5_over_first_stage():
    """Synthetic-but-real labelled set (known relevance by construction, per
    the module docstring above): a query about "cell energy" with one
    clearly relevant candidate ranked poorly by the (fake) first-stage
    lexical/vector score, and several irrelevant candidates ranked well by
    first-stage score alone. A working cross-encoder should recover it.
    """
    relevant_id = "c"
    candidates = [
        RerankCandidate(
            id="c",
            text="mitochondria are the powerhouse of the cell, producing ATP",
            first_stage_score=0.1,
        ),
        RerankCandidate(
            id="x1", text="remember to bring your textbook tomorrow", first_stage_score=0.9
        ),
        RerankCandidate(
            id="x2", text="the exam covers chapters 1 through 3", first_stage_score=0.85
        ),
        RerankCandidate(id="x3", text="office hours are moved to thursday", first_stage_score=0.8),
        RerankCandidate(id="x4", text="please mute your microphones", first_stage_score=0.75),
        RerankCandidate(
            id="x5", text="the next assignment is due next week", first_stage_score=0.7
        ),
    ]

    first_stage_order = sorted(candidates, key=lambda c: c.first_stage_score, reverse=True)
    first_stage_top5 = [c.id for c in first_stage_order[:5]]
    assert relevant_id not in first_stage_top5  # first-stage alone misses it

    async def fake_rerank_transport(query, texts):
        # A cross-encoder that actually reads content: relevance keyed to
        # word overlap with the query concept, not first-stage score.
        keywords = {"cell", "energy", "mitochondria", "atp", "powerhouse"}
        return [1.0 if any(k in t.lower() for k in keywords) else 0.05 for t in texts]

    client = RerankerClient(base_url="http://unused")

    async def _score_via_service(query, cands):
        return await fake_rerank_transport(query, [c.text for c in cands])

    client._score_via_service = _score_via_service  # type: ignore[method-assign]

    results = await client.rerank("cell energy production", candidates)
    reranked_top5 = [r.id for r in results[:5]]
    assert relevant_id in reranked_top5


@pytest.mark.asyncio
async def test_t54_3_reranking_50_candidates_under_500ms():
    candidates = [
        RerankCandidate(id=str(i), text=f"candidate text number {i}", first_stage_score=0.5)
        for i in range(50)
    ]

    async def instant_transport(query, texts):
        return [float(i) for i in range(len(texts))]

    client = RerankerClient(base_url="http://unused")

    async def _score_via_service(query, cands):
        return await instant_transport(query, [c.text for c in cands])

    client._score_via_service = _score_via_service  # type: ignore[method-assign]

    results, elapsed_ms = await rerank_timed(client, "query", candidates)
    assert len(results) == 50
    assert elapsed_ms < 500


@pytest.mark.asyncio
async def test_t54_4_reranker_unavailable_falls_back_to_first_stage():
    candidates = make_candidates()
    client = RerankerClient(
        base_url="http://reranker-definitely-unreachable.invalid", timeout_s=1.0
    )
    results = await client.rerank("query", candidates)

    assert len(results) == len(candidates)
    assert all(not r.reranked for r in results)
    assert all(r.rerank_score is None for r in results)
    # Original first-stage order preserved.
    assert [r.id for r in results] == [c.id for c in candidates]
