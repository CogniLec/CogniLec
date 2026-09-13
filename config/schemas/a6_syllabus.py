"""S50 — A6 syllabus extraction output schema.

Kept separate from ``src.services.llm.schema_registry.AgentID.A6`` (the S38
registry's "A6" is the progress-analyst persona wired up in Block 7/8) to
avoid colliding agent identifiers - see the syllabus extraction agent's
module docstring in ``src/services/syllabus/extraction_agent.py`` for the
naming note.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

MAX_HIERARCHY_DEPTH = 5
MAX_ITEMS_PER_TRANSCRIPT = 200


class ItemType(StrEnum):
    MODULE = "module"
    TOPIC = "topic"
    SUBTOPIC = "subtopic"
    ASSESSMENT = "assessment"
    REFERENCE = "reference"
    SCHEDULE = "schedule"


class ExtractedSyllabusItem(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    item_type: ItemType
    ordinal: int = Field(..., ge=0)
    parent_ordinal: int | None = Field(None, ge=0)
    description: str | None = Field(None, max_length=5000)
    weight_pct: float | None = Field(None, ge=0.0, le=100.0)
    week_number: int | None = Field(None, ge=1)
    references: list[str] = Field(default_factory=list, max_length=20)


class A6SyllabusOutput(BaseModel):
    items: list[ExtractedSyllabusItem] = Field(..., max_length=MAX_ITEMS_PER_TRANSCRIPT)
    subject_title: str = Field(..., min_length=1, max_length=500)
    extraction_confidence: float = Field(..., ge=0.0, le=1.0)
    grade_of_authority: int = Field(..., ge=1, le=5)
