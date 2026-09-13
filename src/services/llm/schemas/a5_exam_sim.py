from __future__ import annotations

from pydantic import BaseModel, Field


class A5Output(BaseModel):
    question: str = Field(..., min_length=10, max_length=2000)
    question_type: str = Field(..., pattern="^(mcq|short_answer|essay|true_false)$")
    options: list[str] | None = Field(None, min_length=2, max_length=6)
    correct_answer: str = Field(..., min_length=1)
    explanation: str = Field(..., min_length=10, max_length=1000)
    difficulty: str = Field(..., pattern="^(easy|medium|hard)$")
    topic_tags: list[str] = Field(..., min_length=1, max_length=5)
