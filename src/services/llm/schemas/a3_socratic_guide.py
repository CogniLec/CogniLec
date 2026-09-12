from __future__ import annotations

from pydantic import BaseModel, Field


class A3Output(BaseModel):
    response_type: str = Field(..., pattern="^(hint|question|feedback|corrective)$")
    content: str = Field(..., min_length=5, max_length=1500)
    student_reasoning_assessment: str = Field(
        ..., pattern="^(correct|partial|misconception|empty)$"
    )
    next_prompt_strategy: str = Field(..., pattern="^(scaffold|probe|redirect|confirm)$")
