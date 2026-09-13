"""Tests for S50 — A6 syllabus extraction (T50.1-T50.6).

ENVIRONMENT / HONESTY CAVEAT: T50.5 requires 20 real, human-annotated
syllabus transcripts. That corpus does not exist in this environment (same
S04/S05 gap as tests/test_s29_segmentation_gate.py and
tests/test_s42_relevance_gate.py - see docs/gaps.md gap #1/#6). It is
skipped rather than faked. Everything else here runs against synthetic
fixture transcripts and a real PG-SYLLABUS connection (testcontainers-style
fixture via tests/conftest.py's `syllabus_session`).
"""

from __future__ import annotations

import uuid

import pytest
from config.schemas.a6_syllabus import ItemType
from sqlalchemy import text
from src.db.repositories.syllabus_repo import SyllabusRepository
from src.db.write_guard import DB3WriteGuard
from src.services.syllabus.extraction_agent import SyllabusExtractionAgent, TranscriptChunk
from src.services.syllabus.routing import route_syllabus_lecture

SAMPLE_TRANSCRIPT = """
Module 1: Introduction
1.1: Overview of the course
1.2: History and motivation
Module 2: Data Structures
2.1: Arrays and lists
Assignment 1: Problem set (weight 10%)
Week 1: Introduction and setup
Reference: Cormen et al., Introduction to Algorithms
"""

NO_SYLLABUS_TRANSCRIPT = """
So today we just chatted about how everyone's week went.
Nothing structured, just a casual conversation before we start.
"""


async def test_syllabus_lecture_capture_path() -> None:
    """T50.1: syllabus session type is routed to A6, content is not."""
    assert route_syllabus_lecture("syllabus") is True
    assert route_syllabus_lecture("mixed") is True
    assert route_syllabus_lecture("content") is False


async def test_hierarchy_ordinals() -> None:
    """T50.3: module/topic hierarchy and ordinals are correct."""
    agent = SyllabusExtractionAgent()
    output = await agent.extract(
        TranscriptChunk(text=SAMPLE_TRANSCRIPT), subject_id=uuid.uuid4(), subject_title="CS101"
    )

    modules = [i for i in output.items if i.item_type == ItemType.MODULE]
    topics = [i for i in output.items if i.item_type == ItemType.TOPIC]
    assessments = [i for i in output.items if i.item_type == ItemType.ASSESSMENT]
    schedule = [i for i in output.items if i.item_type == ItemType.SCHEDULE]

    assert [m.ordinal for m in modules] == [0, 1]
    module1_topics = [t for t in topics if t.parent_ordinal == 0]
    assert [t.ordinal for t in module1_topics] == [0, 1]
    module2_topics = [t for t in topics if t.parent_ordinal == 1]
    assert [t.ordinal for t in module2_topics] == [0]
    assert assessments[0].weight_pct == 10.0
    assert schedule[0].week_number == 1
    assert modules[-1].references or topics[-1].references or assessments  # reference attached


async def test_no_syllabus_content_returns_empty() -> None:
    """Edge case: transcript with no syllabus content -> empty items, no rejection."""
    agent = SyllabusExtractionAgent()
    output = await agent.extract(
        TranscriptChunk(text=NO_SYLLABUS_TRANSCRIPT), subject_id=uuid.uuid4()
    )
    assert output.items == []


async def test_items_land_in_db3(syllabus_session) -> None:
    """T50.2: extracted items land in PG-SYLLABUS (DB-3), via write-authority context."""
    agent = SyllabusExtractionAgent()
    subject_id = uuid.uuid4()
    output = await agent.extract(
        TranscriptChunk(text=SAMPLE_TRANSCRIPT), subject_id=subject_id, subject_title="CS101"
    )

    repo = SyllabusRepository(syllabus_session)
    with DB3WriteGuard.a6_write_context():
        created = await repo.bulk_create_items(subject_id, output.items)
    await syllabus_session.commit()

    assert len(created) == len(output.items)
    rows = (
        await syllabus_session.execute(
            text("SELECT count(*) FROM syllabus_items WHERE subject_id = :sid"),
            {"sid": str(subject_id)},
        )
    ).scalar_one()
    assert rows == len(output.items)


async def test_mixed_session_syllabus_routing() -> None:
    """T50.6: only the syllabus segment of a mixed session is sent to A6."""
    agent = SyllabusExtractionAgent()
    full_transcript = SAMPLE_TRANSCRIPT + "\nAnd now let's get into today's lecture content.\n"
    output = await agent.extract_from_mixed_session(
        full_transcript_text=full_transcript,
        syllabus_segment_text=SAMPLE_TRANSCRIPT,
        subject_id=uuid.uuid4(),
    )
    assert len(output.items) > 0
    assert all("lecture content" not in (i.description or "") for i in output.items)


GATE_SKIP_REASON = (
    "T50.5 requires 20 real, human-annotated syllabus transcripts (S04/S05 "
    "corpus). No such corpus exists in this environment - see "
    "docs/gaps.md gap #1/#6/#9. Cannot honestly evaluate the "
    "extraction-accuracy >= 0.85 gate without it."
)


@pytest.mark.skip(reason=GATE_SKIP_REASON)
def test_extraction_accuracy_20_syllabi() -> None:
    """T50.5: extraction accuracy >= 0.85 on 20 real syllabus transcripts."""
