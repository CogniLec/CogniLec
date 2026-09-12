from __future__ import annotations

from pydantic import BaseModel, Field


class A1Output(BaseModel):
    explanation: str = Field(..., min_length=10, max_length=2000)
    key_concepts: list[str] = Field(..., min_length=1, max_length=10)
    difficulty: str = Field(..., pattern="^(easy|medium|hard)$")
    follow_up_question: str | None = Field(None, max_length=500)
    confidence: float = Field(..., ge=0.0, le=1.0)
