"""Tests for S44 - A2 note synthesis (T44.1-T44.3, T44.6-T44.8).

T44.4 (human review >=4/5 on 10 sessions) and T44.5 (head-to-head human
comparison vs segment-by-segment) require real lecture sessions and human
raters; they are not exercisable as a backend pytest and are skipped below,
mirroring `tests/test_transcript_api.py`'s handling of T24.3/T24.4.
"""

from __future__ import annotations

import json

import pytest
from src.services.llm.router import LLMResponse, LLMRouter, LLMRouterConfig, LLMTier, TierConfig
from src.services.synthesis.note_synthesis import (
    NoteSynthesisAgent,
    NoteSynthesisError,
    RelevantUtterance,
    SessionSynthesisContext,
    validate_hierarchy,
    validate_katex,
    validate_mermaid_blocks,
)

pytestmark = pytest.mark.asyncio

HUMAN_REVIEW_SKIP_REASON = (
    "Requires a human rater panel and real lecture sessions - not exercisable as a backend pytest."
)


def make_agent(sections_json: str) -> NoteSynthesisAgent:
    config = LLMRouterConfig(
        tiers=[TierConfig(tier=LLMTier.TIER_1, model="m", endpoint="http://x")]
    )

    async def transport(tier, messages, timeout_s, schema=None):
        return LLMResponse(
            content=sections_json,
            tier_used=tier.tier,
            model=tier.model,
            latency_ms=1,
            tokens_used=1,
        )

    return NoteSynthesisAgent(LLMRouter(config, transport=transport))


def make_context() -> SessionSynthesisContext:
    return SessionSynthesisContext(
        session_id="s1",
        utterances=[
            RelevantUtterance(id="u1", seq=0, text="Photosynthesis converts light to energy"),
            RelevantUtterance(id="u2", seq=1, text="Chlorophyll absorbs red and blue light"),
        ],
    )


async def test_t44_1_notes_produced_with_valid_hierarchy_and_ordering():
    sections = json.dumps(
        [
            {
                "heading": "Overview",
                "body_md": "Intro.",
                "depth": 0,
                "ordinal": 0,
                "source_utt_ids": ["u1"],
            },
            {
                "heading": "Detail",
                "body_md": "More.",
                "depth": 1,
                "ordinal": 1,
                "source_utt_ids": ["u2"],
            },
        ]
    )
    agent = make_agent(sections)
    result = await agent.synthesize(make_context())
    assert [s.ordinal for s in result] == [0, 1]


async def test_t44_2_every_section_carries_provenance():
    sections = json.dumps(
        [
            {
                "heading": "Overview",
                "body_md": "Intro.",
                "depth": 0,
                "ordinal": 0,
                "source_utt_ids": ["u1"],
            }
        ]
    )
    agent = make_agent(sections)
    result = await agent.synthesize(make_context())
    assert all(len(s.source_utt_ids) >= 1 for s in result)


async def test_t44_3_provenance_ids_reference_relevant_utterances_only():
    """When EVERY section cites an unknown utterance, nothing survives and
    synthesis genuinely fails -- see the sibling test below for the
    partial-failure case (docs/gaps.md #33g), where only the offending
    section is dropped and valid siblings still persist."""
    sections = json.dumps(
        [
            {
                "heading": "Overview",
                "body_md": "Intro.",
                "depth": 0,
                "ordinal": 0,
                "source_utt_ids": ["u_unknown"],
            }
        ]
    )
    agent = make_agent(sections)
    with pytest.raises(NoteSynthesisError, match="no valid sections"):
        await agent.synthesize(make_context())


async def test_t44_3b_one_hallucinated_citation_drops_only_that_section():
    """Regression for docs/gaps.md #33g: a real recording produced 0
    flashcards because one section citing a hallucinated utterance ID
    discarded the entire batch, valid sections included. Now only the
    offending section is dropped; the valid one survives."""
    sections = json.dumps(
        [
            {
                "heading": "Good Section",
                "body_md": "Real content.",
                "depth": 0,
                "ordinal": 0,
                "source_utt_ids": ["u1"],
            },
            {
                "heading": "Hallucinated Section",
                "body_md": "Fabricated content.",
                "depth": 0,
                "ordinal": 1,
                "source_utt_ids": ["u_unknown"],
            },
        ]
    )
    agent = make_agent(sections)
    result = await agent.synthesize(make_context())
    assert len(result) == 1
    assert result[0].heading == "Good Section"


@pytest.mark.skip(reason=HUMAN_REVIEW_SKIP_REASON)
async def test_t44_4_human_review_rating():
    raise NotImplementedError


@pytest.mark.skip(reason=HUMAN_REVIEW_SKIP_REASON)
async def test_t44_5_full_context_beats_segment_by_segment():
    raise NotImplementedError


async def test_t44_6_mermaid_blocks_must_be_nonempty():
    assert validate_mermaid_blocks("some text\n```mermaid\ngraph TD; A-->B;\n```\nmore") is True
    assert validate_mermaid_blocks("```mermaid\n\n```") is False


async def test_t44_7_katex_must_be_balanced():
    assert validate_katex("the formula $E=mc^2$ holds") is True
    assert validate_katex("the formula $E=mc^2 holds") is False
    assert validate_katex("block form $$\\int_0^1 x\\,dx$$ done") is True


async def test_t44_8_no_discarded_utterance_appears_in_notes():
    sections = json.dumps(
        [
            {
                "heading": "Overview",
                "body_md": "Intro.",
                "depth": 0,
                "ordinal": 0,
                "source_utt_ids": ["u1", "discarded"],
            }
        ]
    )
    agent = make_agent(sections)
    with pytest.raises(NoteSynthesisError):
        await agent.synthesize(make_context())


def test_validate_hierarchy_rejects_duplicate_ordinals():
    from src.services.synthesis.note_synthesis import NoteSectionOutput

    sections = [
        NoteSectionOutput(heading="a", body_md="x", depth=0, ordinal=0, source_utt_ids=["u1"]),
        NoteSectionOutput(heading="b", body_md="x", depth=0, ordinal=0, source_utt_ids=["u2"]),
    ]
    assert validate_hierarchy(sections) is False
