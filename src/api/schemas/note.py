"""Pydantic schemas - Note read API (S46)."""

from __future__ import annotations

import uuid

from pydantic import BaseModel


class NoteSectionResponse(BaseModel):
    id: uuid.UUID
    topic_id: uuid.UUID | None
    session_id: uuid.UUID | None
    heading: str
    body_md: str
    depth: int
    ordinal: int
    source_utt_ids: list[uuid.UUID] = []

    @classmethod
    def from_row(cls, row: object, provenance: list[uuid.UUID]) -> NoteSectionResponse:
        mapping = row._mapping  # type: ignore[attr-defined]
        return cls(
            id=mapping["id"],
            topic_id=mapping["topic_id"],
            session_id=mapping["session_id"],
            heading=mapping["heading"],
            body_md=mapping["body_md"],
            depth=mapping["depth"],
            ordinal=mapping["ordinal"],
            source_utt_ids=provenance,
        )


class SessionNotesResponse(BaseModel):
    session_id: uuid.UUID
    subject_id: uuid.UUID
    notes_ready: bool
    sections: list[NoteSectionResponse]


class ConsolidatedTopicNotesResponse(BaseModel):
    topic_id: uuid.UUID
    subject_id: uuid.UUID
    session_ids: list[uuid.UUID]
    sections: list[NoteSectionResponse]
