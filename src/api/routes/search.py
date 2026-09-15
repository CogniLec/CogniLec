"""FastAPI router - hybrid search API (S48).

RLS-scoped the same way as `notes.py`/`transcript.py`: a subject belonging
to another user is invisible under RLS, so a cross-user request 404s. Query
scoping to `subject_id` also happens unconditionally inside
`hybrid_search()` itself (every candidate query has `WHERE subject_id =
:subject_id`), so cross-subject leakage can't happen even where RLS is
bypassed (see docs/gaps.md #4).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies.auth import get_db_session_with_rls
from src.api.schemas.search import SearchResponse, SearchResultResponse
from src.core.config import get_settings
from src.db.exceptions import SubjectNotFoundError
from src.db.repositories.subject_repo import SubjectRepository
from src.ml.embedding.client import EmbeddingClient
from src.services.search.hybrid_search import DEFAULT_LIMIT, hybrid_search

router = APIRouter(tags=["search"])


async def _get_query_embedding(query: str) -> list[float] | None:
    """Best-effort query embedding; a degraded embedding service falls back to lexical-only."""
    try:
        settings = get_settings()
        client = EmbeddingClient(
            tei_base_url=settings.TEI_BASE_URL,
            local_device=f"cuda:{settings.EMBEDDING_CUDA_DEVICE}",
        )
        vectors = await client.embed([query], task_mode="retrieval")
        return vectors[0] if vectors else None
    except Exception:
        return None


@router.get("/subjects/{subject_id}/search", response_model=SearchResponse)
async def search_subject(
    subject_id: uuid.UUID,
    q: str = Query(min_length=1, max_length=500),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=100),
    include_notes: bool = True,
    db: AsyncSession = Depends(get_db_session_with_rls),
) -> SearchResponse:
    try:
        await SubjectRepository(db).get_or_raise(subject_id)
    except SubjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Subject not found"
        ) from exc

    query_embedding = await _get_query_embedding(q)
    results = await hybrid_search(
        db,
        subject_id=subject_id,
        query=q,
        query_embedding=query_embedding,
        limit=limit,
        include_notes=include_notes,
    )
    return SearchResponse(
        subject_id=subject_id,
        query=q,
        results=[SearchResultResponse.from_result(r) for r in results],
    )
