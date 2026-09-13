"""Tests for S43 - A1 ensemble voting (T43.1-T43.5)."""

from __future__ import annotations

import json

import pytest
from src.services.filtering.ensemble_voting import (
    AmbiguityBand,
    EnsembleVotingFilter,
    is_ambiguous,
    vote,
)
from src.services.filtering.relevance_filter import RelevanceFilterAgent, UtteranceInput
from src.services.llm.router import LLMResponse, LLMRouter, LLMRouterConfig, LLMTier, TierConfig


def make_agent(seq_to_relevant: dict[int, bool]) -> RelevanceFilterAgent:
    config = LLMRouterConfig(
        tiers=[TierConfig(tier=LLMTier.TIER_1, model="m", endpoint="http://x")]
    )

    async def transport(tier, messages, timeout_s):
        payload = json.loads(messages[1]["content"])
        seqs = [u["seq"] for u in payload["utterances"]]
        content = json.dumps(
            [
                {
                    "seq": s,
                    "is_relevant": seq_to_relevant[s],
                    "category": "core_content",
                    "filter_reason": "vote",
                    "confidence": 0.6,
                }
                for s in seqs
            ]
        )
        return LLMResponse(
            content=content, tier_used=tier.tier, model=tier.model, latency_ms=1, tokens_used=1
        )

    return RelevanceFilterAgent(LLMRouter(config, transport=transport))


def test_is_ambiguous_respects_band():
    band = AmbiguityBand(low=0.4, high=0.6)
    assert is_ambiguous(UtteranceInput(seq=0, text="x", outlier_score=0.5), band)
    assert not is_ambiguous(UtteranceInput(seq=0, text="x", outlier_score=0.9), band)
    assert not is_ambiguous(UtteranceInput(seq=0, text="x", outlier_score=None), band)


def test_vote_majority():
    is_relevant, needs_review = vote([True, True, False])
    assert is_relevant is True
    assert needs_review is False


def test_t43_2_split_vote_keeps_and_flags_never_discards():
    is_relevant, needs_review = vote([True, False])
    assert is_relevant is True
    assert needs_review is True


@pytest.mark.asyncio
async def test_t43_1_ensemble_available_for_ambiguous_band():
    utterances = [UtteranceInput(seq=0, text="borderline", outlier_score=0.5)]
    agent_a = make_agent({0: True})
    agent_b = make_agent({0: False})
    ensemble = EnsembleVotingFilter([agent_a, agent_b])

    results = await ensemble.classify_ambiguous("Topic", utterances)

    assert results[0].needs_review is True
    assert results[0].is_relevant is True


@pytest.mark.asyncio
async def test_t43_3_zero_band_degenerates_to_no_ensemble_calls():
    utterances = [UtteranceInput(seq=0, text="clear", outlier_score=0.9)]
    ensemble = EnsembleVotingFilter([make_agent({0: True})], band=AmbiguityBand(low=1.0, high=0.0))

    results = await ensemble.classify_ambiguous("Topic", utterances)

    assert results == {}


@pytest.mark.asyncio
async def test_t43_4_models_vote_independently():
    calls: list[list[int]] = []
    utterances = [UtteranceInput(seq=0, text="x", outlier_score=0.5)]

    def make_recording_agent(relevant: bool):
        config = LLMRouterConfig(
            tiers=[TierConfig(tier=LLMTier.TIER_1, model="m", endpoint="http://x")]
        )

        async def transport(tier, messages, timeout_s):
            calls.append([m["content"] for m in messages])
            content = json.dumps(
                [
                    {
                        "seq": 0,
                        "is_relevant": relevant,
                        "category": "core_content",
                        "filter_reason": "x",
                        "confidence": 0.5,
                    }
                ]
            )
            return LLMResponse(
                content=content, tier_used=tier.tier, model=tier.model, latency_ms=1, tokens_used=1
            )

        return RelevanceFilterAgent(LLMRouter(config, transport=transport))

    ensemble = EnsembleVotingFilter([make_recording_agent(True), make_recording_agent(False)])
    await ensemble.classify_ambiguous("Topic", utterances)

    # Each agent's transport was invoked exactly once, independently - never
    # chained through the other agent's output.
    assert len(calls) == 2


def test_ambiguity_band_configurable_default():
    band = AmbiguityBand()
    assert band.low == 0.4
    assert band.high == 0.6
