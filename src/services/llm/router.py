"""S37 — LLM router with five-tier local-first failover ladder.

Tier1 local GPU (vLLM) -> Tier2 local CPU (llama.cpp) -> Tier3 hosted API ->
Tier4 hosted cheap API -> Tier5 FAIL (session marked failed, never silently
succeeds).
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from enum import StrEnum

import httpx  # type: ignore[import-not-found]
from pydantic import BaseModel, Field


class LLMTier(StrEnum):
    TIER_1 = "tier_1"
    TIER_2 = "tier_2"
    TIER_3 = "tier_3"
    TIER_4 = "tier_4"
    TIER_5 = "tier_5"


class FailoverTrigger(StrEnum):
    HTTP_ERROR = "http_error"
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    SCHEMA_INVALID = "schema_invalid"


class TierConfig(BaseModel):
    tier: LLMTier
    model: str
    endpoint: str
    api_key_env: str | None = None
    timeout_s: int = 60
    max_retries: int = 0


DEFAULT_TIMEOUT_BY_TIER: dict[LLMTier, int] = {
    LLMTier.TIER_1: 60,
    LLMTier.TIER_2: 120,
    LLMTier.TIER_3: 30,
    LLMTier.TIER_4: 30,
}


class LLMRouterConfig(BaseModel):
    tiers: list[TierConfig]
    timeout_by_tier: dict[LLMTier, int] = Field(
        default_factory=lambda: dict(DEFAULT_TIMEOUT_BY_TIER)
    )


class RoutingDecision(BaseModel):
    tier: LLMTier
    model: str
    attempt: int
    trigger: FailoverTrigger | None = None
    timestamp: datetime


class LLMResponse(BaseModel):
    content: str
    tier_used: LLMTier
    model: str
    latency_ms: int
    tokens_used: int
    failed: bool = False
    failure_reason: str | None = None


class TierFailureError(Exception):
    """Raised by a tier transport to signal a failover-worthy failure."""

    def __init__(self, trigger: FailoverTrigger, message: str) -> None:
        super().__init__(message)
        self.trigger = trigger
        self.message = message


TierTransport = Callable[[TierConfig, list[dict[str, str]], int], Awaitable[LLMResponse]]


async def default_http_transport(
    tier: TierConfig, messages: list[dict[str, str]], timeout_s: int
) -> LLMResponse:
    """Real OpenAI-compatible transport used against vllm/llama.cpp/hosted APIs."""
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.post(
                f"{tier.endpoint.rstrip('/')}/chat/completions",
                json={"model": tier.model, "messages": messages},
            )
    except httpx.TimeoutException as exc:
        raise TierFailureError(FailoverTrigger.TIMEOUT, str(exc)) from exc
    except httpx.HTTPError as exc:
        raise TierFailureError(FailoverTrigger.HTTP_ERROR, str(exc)) from exc

    latency_ms = int((time.monotonic() - start) * 1000)
    if resp.status_code == 429:
        raise TierFailureError(FailoverTrigger.RATE_LIMIT, "rate limited")
    if resp.status_code >= 400:
        raise TierFailureError(FailoverTrigger.HTTP_ERROR, f"http {resp.status_code}")

    body = resp.json()
    content = body["choices"][0]["message"]["content"]
    usage = body.get("usage", {})
    return LLMResponse(
        content=content,
        tier_used=tier.tier,
        model=tier.model,
        latency_ms=latency_ms,
        tokens_used=usage.get("total_tokens", 0),
    )


class LLMRouter:
    """Chain-of-responsibility failover ladder across the five LLM tiers."""

    def __init__(
        self,
        config: LLMRouterConfig,
        transport: TierTransport = default_http_transport,
        on_tier_recorded: Callable[[RoutingDecision], None] | None = None,
    ) -> None:
        self._config = config
        self._transport = transport
        self._on_tier_recorded = on_tier_recorded

    async def complete(
        self,
        messages: list[dict[str, str]],
        agent_id: str,
        prompt_version: str,
        schema: dict[str, object] | None = None,
    ) -> LLMResponse:
        last_trigger: FailoverTrigger | None = None
        last_tier: LLMTier | None = None

        for attempt, tier in enumerate(self._config.tiers, start=1):
            timeout_s = self._config.timeout_by_tier.get(tier.tier, tier.timeout_s)
            decision = RoutingDecision(
                tier=tier.tier,
                model=tier.model,
                attempt=attempt,
                trigger=last_trigger,
                timestamp=datetime.now(UTC),
            )
            if self._on_tier_recorded is not None:
                self._on_tier_recorded(decision)

            try:
                response = await self._try_tier(tier, messages, timeout_s)
            except TierFailureError as exc:
                last_trigger = exc.trigger
                last_tier = tier.tier
                continue

            return response

        return LLMResponse(
            content="",
            tier_used=LLMTier.TIER_5,
            model="",
            latency_ms=0,
            tokens_used=0,
            failed=True,
            failure_reason=(
                f"All tiers exhausted after {last_trigger.value if last_trigger else 'unknown'}"
                f" at {last_tier.value if last_tier else 'unknown'}"
            ),
        )

    async def _try_tier(
        self, tier: TierConfig, messages: list[dict[str, str]], timeout: int
    ) -> LLMResponse:
        return await self._transport(tier, messages, timeout)
