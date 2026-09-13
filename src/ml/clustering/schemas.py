"""S30 — Pydantic schemas for topic clustering."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TopicCreate(BaseModel):
    session_id: uuid.UUID | None = None
    centroid: list[float]
    label: str | None = None
    keywords: list[str] = []
    keyword_scores: list[float] = []
    segment_count: int = 0
    utterance_count: int = 0


class TopicResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    subject_id: uuid.UUID
    session_id: uuid.UUID | None
    centroid: list[float]
    label: str | None
    keywords: list[str] | None
    is_user_edited: bool
    segment_count: int
    utterance_count: int
    created_at: datetime


class SegmentTopicAssignment(BaseModel):
    segment_id: uuid.UUID
    topic_id: uuid.UUID | None
    outlier_score: float
    is_outlier: bool


class ClusteringResult(BaseModel):
    session_id: uuid.UUID
    topics_created: int
    segments_assigned: int
    outliers: int
    topic_assignments: list[SegmentTopicAssignment]
