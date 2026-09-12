from __future__ import annotations

from pydantic import BaseModel, Field


class A4Output(BaseModel):
    plan_summary: str = Field(..., min_length=10, max_length=1000)
    tasks: list[str] = Field(..., min_length=1, max_length=20)
    estimated_minutes: int = Field(..., ge=1, le=600)
