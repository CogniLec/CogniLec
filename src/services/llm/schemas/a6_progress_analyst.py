from __future__ import annotations

from pydantic import BaseModel, Field


class A6Output(BaseModel):
    summary: str = Field(..., min_length=10, max_length=2000)
    mastery_scores: dict[str, float] = Field(..., min_length=1)
    recommended_next_topics: list[str] = Field(..., min_length=0, max_length=10)
