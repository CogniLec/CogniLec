"""Pydantic schemas - Subject."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _reject_blank(value: str | None) -> str | None:
    if value is not None and not value.strip():
        msg = "name must not be blank"
        raise ValueError(msg)
    return value


class SubjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(None, max_length=2000)

    _validate_name = field_validator("name")(_reject_blank)


class SubjectUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=2000)

    _validate_name = field_validator("name")(_reject_blank)


class SubjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime


class SubjectList(BaseModel):
    items: list[SubjectResponse]
    total: int
