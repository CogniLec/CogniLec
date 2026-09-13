"""S52 — Pydantic models for coverage mapping."""

from __future__ import annotations

import uuid
from enum import StrEnum

from pydantic import BaseModel, Field

AUTO_THRESHOLD = 0.80
SUGGEST_THRESHOLD = 0.60


class CoverageStatus(StrEnum):
    NOT_STARTED = "not_started"
    PARTIAL = "partial"
    COVERED = "covered"


class AlignmentConfidence(StrEnum):
    AUTO = "auto"
    SUGGESTED = "suggested"
    NONE = "none"


class TopicSyllabusAlignment(BaseModel):
    topic_id: uuid.UUID
    syllabus_item_id: uuid.UUID
    cosine_similarity: float = Field(..., ge=0.0, le=1.0)
    confidence: AlignmentConfidence
    auto_aligned: bool


class SyllabusItemCoverageDetail(BaseModel):
    item_id: uuid.UUID
    title: str
    item_type: str
    ordinal: int
    parent_id: uuid.UUID | None
    coverage_status: CoverageStatus
    covered_by_topics: list[uuid.UUID]
    alignment_confidence: AlignmentConfidence | None = None


class SyllabusCoverageSummary(BaseModel):
    subject_id: uuid.UUID
    total_items: int
    covered_items: int
    partial_items: int
    not_started_items: int
    coverage_pct: float = Field(..., ge=0.0, le=100.0)
    items: list[SyllabusItemCoverageDetail]


class AlignmentCorrection(BaseModel):
    topic_id: uuid.UUID
    syllabus_item_id: uuid.UUID
    action: str = Field(..., pattern="^(link|unlink|replace)$")
    replace_with_item_id: uuid.UUID | None = None


def classify_similarity(cosine: float) -> AlignmentConfidence:
    if cosine >= AUTO_THRESHOLD:
        return AlignmentConfidence.AUTO
    if cosine >= SUGGEST_THRESHOLD:
        return AlignmentConfidence.SUGGESTED
    return AlignmentConfidence.NONE
