"""Subject request/response schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SubjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(None, max_length=2000)


class SubjectUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=2000)


class SubjectResponse(BaseModel):
    id: UUID
    name: str
    description: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SubjectList(BaseModel):
    items: list[SubjectResponse]
    total: int
