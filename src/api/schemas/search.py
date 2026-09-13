"""Pydantic schemas - Hybrid search API (S48)."""

from __future__ import annotations

import uuid

from pydantic import BaseModel

from src.services.search.hybrid_search import SearchResult


class SearchResultResponse(BaseModel):
    source_type: str
    id: uuid.UUID
    session_id: uuid.UUID | None
    text: str
    lexical_rank: int | None
    vector_rank: int | None
    rrf_score: float

    @classmethod
    def from_result(cls, result: SearchResult) -> SearchResultResponse:
        return cls(
            source_type=result.source_type.value,
            id=result.id,
            session_id=result.session_id,
            text=result.text,
            lexical_rank=result.lexical_rank,
            vector_rank=result.vector_rank,
            rrf_score=result.rrf_score,
        )


class SearchResponse(BaseModel):
    subject_id: uuid.UUID
    query: str
    results: list[SearchResultResponse]
