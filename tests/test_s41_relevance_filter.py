"""Tests for S41 - A1 relevance filter (T41.1-T41.6)."""

from __future__ import annotations

import json

import pytest
from src.services.filtering.relevance_filter import (
    FilterCategory,
    RelevanceFilterAgent,
    RelevanceFilterError,
    UtteranceInput,
    batch_utterances,
    build_prompt,
    decisions_to_flags,
    parse_decisions,
)
from src.services.llm.router import LLMResponse, LLMRouter, LLMRouterConfig, LLMTier, TierConfig


def make_config() -> LLMRouterConfig:
    return LLMRouterConfig(tiers=[TierConfig(tier=LLMTier.TIER_1, model="m", endpoint="http://x")])


def scripted_router(handler):
    async def _transport(tier, messages, timeout_s):
        return LLMResponse(
            content=handler(messages),
            tier_used=tier.tier,
            model=tier.model,
            latency_ms=1,
            tokens_used=1,
        )

    return LLMRouter(make_config(), transport=_transport)


def decision(seq: int, is_relevant: bool, category: str = "core_content") -> dict:
    return {
        "seq": seq,
        "is_relevant": is_relevant,
        "category": category,
        "filter_reason": "test",
        "confidence": 0.9,
    }


def test_batch_utterances_splits_correctly():
    utterances = [UtteranceInput(seq=i, text=f"u{i}") for i in range(45)]
    batches = batch_utterances(utterances, batch_size=20)
    assert [len(b) for b in batches] == [20, 20, 5]


def test_parse_decisions_rejects_mismatched_seqs():
    with pytest.raises(RelevanceFilterError):
        parse_decisions(json.dumps([decision(1, True)]), expected_seqs={1, 2})


def test_parse_decisions_rejects_non_json():
    with pytest.raises(RelevanceFilterError):
        parse_decisions("not json", expected_seqs={1})


@pytest.mark.asyncio
async def test_t41_1_every_utterance_receives_decision_and_rationale():
    utterances = [UtteranceInput(seq=i, text=f"utterance {i}") for i in range(3)]

    def handler(messages):
        return json.dumps([decision(i, True) for i in range(3)])

    agent = RelevanceFilterAgent(scripted_router(handler))
    decisions = await agent.classify_session("Photosynthesis", utterances)

    assert len(decisions) == 3
    assert all(d.filter_reason for d in decisions)


@pytest.mark.asyncio
async def test_t41_2_relevant_student_question_retained():
    utterances = [
        UtteranceInput(seq=0, text="Lecturer: photosynthesis converts light to chemical energy"),
        UtteranceInput(seq=1, text="Student: does that happen in the mitochondria too?"),
    ]

    def handler(messages):
        return json.dumps(
            [
                decision(0, True, "core_content"),
                decision(1, True, "student_question"),
            ]
        )

    agent = RelevanceFilterAgent(scripted_router(handler))
    decisions = await agent.classify_session("Photosynthesis", utterances)

    student_q = next(d for d in decisions if d.seq == 1)
    assert student_q.is_relevant is True
    assert student_q.category == FilterCategory.STUDENT_QUESTION


@pytest.mark.asyncio
async def test_t41_3_offtopic_lecturer_aside_discarded():
    utterances = [UtteranceInput(seq=0, text="Lecturer: anyway, go Wildcats, big game Friday")]

    def handler(messages):
        return json.dumps([decision(0, False, "aside")])

    agent = RelevanceFilterAgent(scripted_router(handler))
    decisions = await agent.classify_session("Photosynthesis", utterances)

    assert decisions[0].is_relevant is False
    assert decisions[0].category == FilterCategory.ASIDE


def test_t41_4_decisions_to_flags_never_removes_data():
    from src.services.filtering.relevance_filter import RelevanceDecision

    decisions = [
        RelevanceDecision(
            seq=0,
            is_relevant=False,
            category=FilterCategory.ASIDE,
            filter_reason="off-topic",
            confidence=0.8,
        )
    ]
    flags = decisions_to_flags(decisions, outlier_scores={0: 0.7})
    is_relevant, filter_reason, outlier_score = flags[0]
    assert is_relevant is False
    assert filter_reason == "off-topic"
    assert outlier_score == 0.7


def test_t41_5_rationale_is_machine_readable():
    from src.services.filtering.relevance_filter import RelevanceDecision

    d = RelevanceDecision(
        seq=0,
        is_relevant=False,
        category=FilterCategory.ADMIN,
        filter_reason="administrative_announcement",
        confidence=0.95,
    )
    assert isinstance(d.filter_reason, str)
    assert d.model_dump()["category"] == "admin"


@pytest.mark.asyncio
async def test_t41_6_batch_boundaries_do_not_change_decisions():
    utterances = [UtteranceInput(seq=i, text=f"utterance {i}") for i in range(5)]

    def handler(messages):
        payload = json.loads(messages[1]["content"])
        seqs = [u["seq"] for u in payload["utterances"]]
        return json.dumps([decision(s, s % 2 == 0) for s in seqs])

    agent_one_batch = RelevanceFilterAgent(scripted_router(handler), batch_size=5)
    agent_small_batches = RelevanceFilterAgent(scripted_router(handler), batch_size=2)

    one_batch = await agent_one_batch.classify_session("Topic", utterances)
    small_batches = await agent_small_batches.classify_session("Topic", utterances)

    by_seq_one = {d.seq: d.is_relevant for d in one_batch}
    by_seq_small = {d.seq: d.is_relevant for d in small_batches}
    assert by_seq_one == by_seq_small


def test_build_prompt_never_includes_speaker_tag():
    utterances = [UtteranceInput(seq=0, text="hello")]
    messages = build_prompt("Topic", utterances)
    assert "speaker_tag" not in json.dumps(messages)
