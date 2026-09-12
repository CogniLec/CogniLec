"""S39 — Pydantic models for agent_runs tracing/cost rows."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class AgentRunStatus(StrEnum):
    STARTED = "started"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


class AgentRun(BaseModel):
    id: str
    session_id: str
    trace_id: str
    agent_id: str
    model: str
    tier: str
    prompt_version: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = Field(default=0.0, ge=0.0)
    latency_ms: int = Field(default=0, ge=0)
    status: AgentRunStatus
    started_at: datetime
    completed_at: datetime | None = None
    error: str | None = None


class TraceContext(BaseModel):
    trace_id: str
    session_id: str
    parent_span_id: str | None = None
