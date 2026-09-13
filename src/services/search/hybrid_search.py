"""S48 — hybrid search: lexical `ts_rank` fused with pgvector cosine via RRF.

Reciprocal Rank Fusion (RRF) combines two independently-ranked result lists
without needing their scores to be on the same scale: each result's fused
score is `sum(1 / (k + rank))` over the lists it appears in, `rank` being
its 1-based position in that list. This is what lets an exact-phrase query
("this will be on the exam") surface via the lexical list even when it
scores poorly in embedding space, while a conceptual query still benefits
from the vector list (T48.1/T48.2).

Every query is scoped to a single `subject_id` (T48.4) - there is no
cross-subject code path here at all, not just a filter that could be
bypassed.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

DEFAULT_RRF_K = 60
DEFAULT_LIMIT = 20
DEFAULT_CANDIDATE_POOL = 50


class SearchSourceType(StrEnum):
    UTTERANCE = "utterance"
    NOTE_SECTION = "note_section"


@dataclass(frozen=True)
class SearchResult:
    source_type: SearchSourceType
    id: uuid.UUID
    session_id: uuid.UUID | None
    text: str
    lexical_rank: int | None
    vector_rank: int | None
    rrf_score: float


async def _lexical_candidates(
    db: AsyncSession, subject_id: uuid.UUID, query: str, limit: int
) -> list[tuple[uuid.UUID, uuid.UUID | None, str]]:
    result = await db.execute(
        text("""
            SELECT id, session_id, text
            FROM utterances
            WHERE subject_id = :subject_id AND text_tsv @@ websearch_to_tsquery('english', :query)
            ORDER BY ts_rank(text_tsv, websearch_to_tsquery('english', :query)) DESC
            LIMIT :limit
        """),
        {"subject_id": subject_id, "query": query, "limit": limit},
    )
    return [(row.id, row.session_id, row.text) for row in result.all()]


async def _lexical_candidates_notes(
    db: AsyncSession, subject_id: uuid.UUID, query: str, limit: int
) -> list[tuple[uuid.UUID, uuid.UUID | None, str]]:
    result = await db.execute(
        text("""
            SELECT id, session_id, heading || ': ' || body_md AS text
            FROM note_sections
            WHERE subject_id = :subject_id AND body_tsv @@ websearch_to_tsquery('english', :query)
            ORDER BY ts_rank(body_tsv, websearch_to_tsquery('english', :query)) DESC
            LIMIT :limit
        """),
        {"subject_id": subject_id, "query": query, "limit": limit},
    )
    return [(row.id, row.session_id, row.text) for row in result.all()]


async def _vector_candidates(
    db: AsyncSession, subject_id: uuid.UUID, embedding: list[float], limit: int
) -> list[tuple[uuid.UUID, uuid.UUID | None, str]]:
    result = await db.execute(
        text("""
            SELECT id, session_id, text
            FROM utterances
            WHERE subject_id = :subject_id AND embedding IS NOT NULL
            ORDER BY embedding <=> :embedding
            LIMIT :limit
        """),
        {"subject_id": subject_id, "embedding": str(embedding), "limit": limit},
    )
    return [(row.id, row.session_id, row.text) for row in result.all()]


async def _vector_candidates_notes(
    db: AsyncSession, subject_id: uuid.UUID, embedding: list[float], limit: int
) -> list[tuple[uuid.UUID, uuid.UUID | None, str]]:
    result = await db.execute(
        text("""
            SELECT id, session_id, heading || ': ' || body_md AS text
            FROM note_sections
            WHERE subject_id = :subject_id AND embedding IS NOT NULL
            ORDER BY embedding <=> :embedding
            LIMIT :limit
        """),
        {"subject_id": subject_id, "embedding": str(embedding), "limit": limit},
    )
    return [(row.id, row.session_id, row.text) for row in result.all()]


def _rrf_fuse(
    source_type: SearchSourceType,
    lexical: list[tuple[uuid.UUID, uuid.UUID | None, str]],
    vector: list[tuple[uuid.UUID, uuid.UUID | None, str]],
    k: int,
) -> dict[uuid.UUID, SearchResult]:
    fused: dict[uuid.UUID, SearchResult] = {}
    lexical_rank = {row[0]: i + 1 for i, row in enumerate(lexical)}
    vector_rank = {row[0]: i + 1 for i, row in enumerate(vector)}
    by_id = {row[0]: row for row in (*lexical, *vector)}

    for item_id in {*lexical_rank, *vector_rank}:
        lrank = lexical_rank.get(item_id)
        vrank = vector_rank.get(item_id)
        score = (1.0 / (k + lrank) if lrank else 0.0) + (1.0 / (k + vrank) if vrank else 0.0)
        _, session_id, item_text = by_id[item_id]
        fused[item_id] = SearchResult(
            source_type=source_type,
            id=item_id,
            session_id=session_id,
            text=item_text,
            lexical_rank=lrank,
            vector_rank=vrank,
            rrf_score=score,
        )
    return fused


async def hybrid_search(
    db: AsyncSession,
    subject_id: uuid.UUID,
    query: str,
    query_embedding: list[float] | None,
    limit: int = DEFAULT_LIMIT,
    candidate_pool: int = DEFAULT_CANDIDATE_POOL,
    rrf_k: int = DEFAULT_RRF_K,
    include_notes: bool = True,
) -> list[SearchResult]:
    """Hybrid retrieval over `utterances` (and `note_sections` when `include_notes`).

    Fuses lexical (`ts_rank`) and dense (pgvector cosine) candidate lists
    per source type via RRF, then merges and re-sorts across source types by
    fused score. `query_embedding` may be `None` (embedding service down) -
    the search degrades to lexical-only rather than failing (T48.6 covers
    both transcripts and notes; degrading gracefully keeps that true even
    under a partial outage).
    """
    lex_utt = await _lexical_candidates(db, subject_id, query, candidate_pool)
    vec_utt = (
        await _vector_candidates(db, subject_id, query_embedding, candidate_pool)
        if query_embedding is not None
        else []
    )
    fused = _rrf_fuse(SearchSourceType.UTTERANCE, lex_utt, vec_utt, rrf_k)

    if include_notes:
        lex_notes = await _lexical_candidates_notes(db, subject_id, query, candidate_pool)
        vec_notes = (
            await _vector_candidates_notes(db, subject_id, query_embedding, candidate_pool)
            if query_embedding is not None
            else []
        )
        fused_notes = _rrf_fuse(SearchSourceType.NOTE_SECTION, lex_notes, vec_notes, rrf_k)
        combined = [*fused.values(), *fused_notes.values()]
    else:
        combined = list(fused.values())

    combined.sort(key=lambda r: r.rrf_score, reverse=True)
    return combined[:limit]
