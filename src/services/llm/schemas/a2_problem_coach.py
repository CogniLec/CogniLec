from __future__ import annotations

from pydantic import BaseModel, Field


class A2Output(BaseModel):
    hint: str = Field(..., min_length=5, max_length=1000)
    step_number: int = Field(..., ge=1)
    is_final_step: bool
    worked_solution: str | None = Field(None, max_length=2000)
