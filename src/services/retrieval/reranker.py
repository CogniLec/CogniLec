"""S54 — Qwen3-Reranker cross-encoder, always-on for A3/A5 two-stage retrieval.

Unlike the LLM router (S37) or embedding client (S25), there is no cost
gating here (v2.0 SS3.4): reranking runs on every A3/A5 retrieval regardless
of tier/budget. The service is still an external dependency though, so a
TEI-style reranker HTTP outage must degrade the pipeline rather than break
it (T54.4) - on failure this returns the first-stage candidates unchanged,
in their original order, rather than raising.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class RerankCandidate:
    id: str
    text: str
    first_stage_score: float


@dataclass(frozen=True)
class RerankResult:
    id: str
    text: str
    first_stage_score: float
    rerank_score: float | None
    reranked: bool


class RerankerClient:
    """Cross-encoder reranker served alongside TEI (Qwen3-Reranker)."""

    def __init__(self, base_url: str = "http://reranker:80", timeout_s: float = 10.0) -> None:
        self.base_url = base_url
        self.timeout_s = timeout_s

    async def rerank(self, query: str, candidates: list[RerankCandidate]) -> list[RerankResult]:
        """Score `candidates` against `query`, highest `rerank_score` first.

        On any transport failure, returns the candidates unranked-by-us but
        preserving first-stage order, with `reranked=False` on every result
        (T54.4) - callers can detect the fallback via that flag without the
        pipeline needing a try/except of its own.
        """
        if not candidates:
            return []
        try:
            scores = await self._score_via_service(query, candidates)
        except (httpx.HTTPError, OSError):
            return [
                RerankResult(
                    id=c.id,
                    text=c.text,
                    first_stage_score=c.first_stage_score,
                    rerank_score=None,
                    reranked=False,
                )
                for c in candidates
            ]

        results = [
            RerankResult(
                id=c.id,
                text=c.text,
                first_stage_score=c.first_stage_score,
                rerank_score=score,
                reranked=True,
            )
            for c, score in zip(candidates, scores, strict=True)
        ]
        results.sort(key=lambda r: r.rerank_score or 0.0, reverse=True)
        return results

    async def _score_via_service(
        self, query: str, candidates: list[RerankCandidate]
    ) -> list[float]:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout_s) as client:
            resp = await client.post(
                "/rerank",
                json={"query": query, "texts": [c.text for c in candidates]},
            )
            resp.raise_for_status()
            payload = resp.json()
            # TEI /rerank response shape: [{"index": int, "score": float}, ...],
            # not necessarily in input order.
            by_index = {item["index"]: item["score"] for item in payload}
            return [by_index[i] for i in range(len(candidates))]


async def rerank_timed(
    client: RerankerClient, query: str, candidates: list[RerankCandidate]
) -> tuple[list[RerankResult], float]:
    """Rerank and report elapsed wall-clock time in milliseconds (T54.3)."""
    start = time.perf_counter()
    results = await client.rerank(query, candidates)
    elapsed_ms = (time.perf_counter() - start) * 1000
    return results, elapsed_ms
