"""S25 — Pydantic schemas for the embedding service."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class EmbeddingRequest(BaseModel):
    texts: list[str]
    task_mode: Literal["retrieval", "clustering"] = "retrieval"
    model_version: str | None = None


class EmbeddingResponse(BaseModel):
    embeddings: list[list[float]]
    model_version: str
    dim: int
    count: int


class BackfillResult(BaseModel):
    subject_id: str
    from_version: str
    to_version: str
    total: int
    updated: int
    resumed_from: int = 0
