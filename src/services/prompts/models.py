"""S40 — Pydantic models for prompt versioning."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class PromptStatus(StrEnum):
    DRAFT = "draft"
    VERSIONED = "versioned"
    TESTED = "tested"
    DEPLOYED = "deployed"
    ARCHIVED = "archived"


class PromptEntry(BaseModel):
    id: str
    agent_id: str
    name: str
    version: str
    content: str
    status: PromptStatus
    model: str | None = None
    temperature: float | None = None
    created_at: datetime
    updated_at: datetime
    changelog: str | None = None


class AgentConfig(BaseModel):
    agent_id: str
    model: str = "phi-3-mini-3.8b-4bit"
    temperature: float = 0.7
    prompt_id: str
    max_tokens: int = 2048


class RegressionResult(BaseModel):
    agent_id: str
    prompt_version: str
    total_cases: int
    passed: int
    failed: int
    pass_rate: float
    failed_cases: list[dict[str, object]] | None = None
