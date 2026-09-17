"""S37 — LLM router failover ladder tests.

Uses a scripted transport (no network/docker dependency) so tests are fast
and deterministic, while exercising the exact same LLMRouter.complete()
descent logic that runs against real tier endpoints in production.
"""

from __future__ import annotations

import pytest
from src.services.llm.router import (
    FailoverTrigger,
    LLMResponse,
    LLMRouter,
    LLMRouterConfig,
    LLMTier,
    RoutingDecision,
    TierConfig,
    TierFailureError,
)


def make_tiers() -> list[TierConfig]:
    return [
        TierConfig(tier=LLMTier.TIER_1, model="phi-3-mini", endpoint="http://vllm:8000/v1"),
        TierConfig(tier=LLMTier.TIER_2, model="llama-cpp", endpoint="http://llamacpp:8080/v1"),
        TierConfig(tier=LLMTier.TIER_3, model="gpt-4o-mini", endpoint="https://api.openai.com/v1"),
        TierConfig(
            tier=LLMTier.TIER_4, model="together-llama3", endpoint="https://api.together.xyz/v1"
        ),
    ]


def scripted_transport(script: dict[LLMTier, TierFailureError | LLMResponse]):
    async def _transport(tier: TierConfig, messages, timeout_s, schema=None):
        outcome = script[tier.tier]
        if isinstance(outcome, TierFailureError):
            raise outcome
        return outcome

    return _transport


def ok_response(tier: LLMTier) -> LLMResponse:
    return LLMResponse(content="hello", tier_used=tier, model="m", latency_ms=10, tokens_used=5)


@pytest.mark.asyncio
async def test_failover_triggers_http_error():
    script = {
        LLMTier.TIER_1: TierFailureError(FailoverTrigger.HTTP_ERROR, "500"),
        LLMTier.TIER_2: ok_response(LLMTier.TIER_2),
    }
    router = LLMRouter(
        LLMRouterConfig(tiers=make_tiers()[:2]), transport=scripted_transport(script)
    )
    result = await router.complete([{"role": "user", "content": "hi"}], "A1", "1.0.0")
    assert result.tier_used == LLMTier.TIER_2
    assert not result.failed


@pytest.mark.asyncio
async def test_failover_triggers_timeout():
    script = {
        LLMTier.TIER_1: TierFailureError(FailoverTrigger.TIMEOUT, "timed out"),
        LLMTier.TIER_2: ok_response(LLMTier.TIER_2),
    }
    router = LLMRouter(
        LLMRouterConfig(tiers=make_tiers()[:2]), transport=scripted_transport(script)
    )
    result = await router.complete([{"role": "user", "content": "hi"}], "A1", "1.0.0")
    assert result.tier_used == LLMTier.TIER_2


@pytest.mark.asyncio
async def test_failover_triggers_rate_limit_no_retry_storm():
    calls: list[LLMTier] = []

    async def transport(tier: TierConfig, messages, timeout_s, schema=None):
        calls.append(tier.tier)
        if tier.tier == LLMTier.TIER_3:
            raise TierFailureError(FailoverTrigger.RATE_LIMIT, "429")
        return ok_response(tier.tier)

    router = LLMRouter(LLMRouterConfig(tiers=make_tiers()[2:]), transport=transport)
    result = await router.complete([{"role": "user", "content": "hi"}], "A1", "1.0.0")
    assert result.tier_used == LLMTier.TIER_4
    # Exactly one attempt at tier_3 — no retry-storming.
    assert calls.count(LLMTier.TIER_3) == 1


@pytest.mark.asyncio
async def test_failover_triggers_schema_invalid():
    script = {
        LLMTier.TIER_1: TierFailureError(FailoverTrigger.SCHEMA_INVALID, "bad json"),
        LLMTier.TIER_2: ok_response(LLMTier.TIER_2),
    }
    router = LLMRouter(
        LLMRouterConfig(tiers=make_tiers()[:2]), transport=scripted_transport(script)
    )
    result = await router.complete([{"role": "user", "content": "hi"}], "A1", "1.0.0")
    assert result.tier_used == LLMTier.TIER_2


@pytest.mark.asyncio
async def test_container_kill_failover_completes_via_fallback():
    """T37.2 (AC-8): killing the primary tier mid-flow must still complete the session."""
    script = {
        LLMTier.TIER_1: TierFailureError(FailoverTrigger.HTTP_ERROR, "connection refused"),
        LLMTier.TIER_2: ok_response(LLMTier.TIER_2),
        LLMTier.TIER_3: ok_response(LLMTier.TIER_3),
        LLMTier.TIER_4: ok_response(LLMTier.TIER_4),
    }
    router = LLMRouter(LLMRouterConfig(tiers=make_tiers()), transport=scripted_transport(script))
    result = await router.complete([{"role": "user", "content": "hi"}], "A1", "1.0.0")
    assert not result.failed
    assert result.tier_used == LLMTier.TIER_2


@pytest.mark.asyncio
async def test_all_tiers_exhausted_marks_failed_never_complete():
    """T37.3 (AC-9): exhausting every tier must yield Tier 5 failure, never a false success."""
    script = {t.tier: TierFailureError(FailoverTrigger.HTTP_ERROR, "down") for t in make_tiers()}
    router = LLMRouter(LLMRouterConfig(tiers=make_tiers()), transport=scripted_transport(script))
    result = await router.complete([{"role": "user", "content": "hi"}], "A1", "1.0.0")
    assert result.failed is True
    assert result.tier_used == LLMTier.TIER_5
    assert result.failure_reason is not None
    assert "exhausted" in result.failure_reason


@pytest.mark.asyncio
async def test_timeout_configurable_per_agent():
    config_a1 = LLMRouterConfig(tiers=make_tiers()[:1], timeout_by_tier={LLMTier.TIER_1: 60})
    config_a2 = LLMRouterConfig(tiers=make_tiers()[:1], timeout_by_tier={LLMTier.TIER_1: 120})
    seen_timeouts: list[int] = []

    async def transport(tier: TierConfig, messages, timeout_s, schema=None):
        seen_timeouts.append(timeout_s)
        return ok_response(tier.tier)

    await LLMRouter(config_a1, transport=transport).complete([], "A1", "1.0.0")
    await LLMRouter(config_a2, transport=transport).complete([], "A2", "1.0.0")
    assert seen_timeouts == [60, 120]


@pytest.mark.asyncio
async def test_tier_recorded_per_invocation():
    recorded: list[RoutingDecision] = []
    script = {
        LLMTier.TIER_1: TierFailureError(FailoverTrigger.HTTP_ERROR, "down"),
        LLMTier.TIER_2: ok_response(LLMTier.TIER_2),
    }
    router = LLMRouter(
        LLMRouterConfig(tiers=make_tiers()[:2]),
        transport=scripted_transport(script),
        on_tier_recorded=recorded.append,
    )
    result = await router.complete([{"role": "user", "content": "hi"}], "A1", "1.0.0")
    assert result.tier_used == LLMTier.TIER_2
    tiers_attempted = [d.tier for d in recorded]
    assert tiers_attempted == [LLMTier.TIER_1, LLMTier.TIER_2]
