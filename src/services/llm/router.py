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

import httpx
from pydantic import BaseModel, Field


def inline_schema_refs(schema: dict[str, object]) -> dict[str, object]:
    """Resolve `$ref`/`$defs` into a flat, self-contained JSON schema.

    Pydantic's `model_json_schema()` always uses `$ref`/`$defs` for nested
    models and enums. vLLM 0.5.5's guided-decoding backend (used for the
    `guided_json` parameter `default_http_transport` forwards below) 500s
    on any schema containing `$ref` -- confirmed live via a direct request
    to both LiteLLM and vLLM itself: the exact same schema with its `$ref`
    inlined works and produces a correctly-constrained response, unchanged
    otherwise. Callers passing `schema=` to `LLMRouter.complete()` should
    run their Pydantic schema through this first. This is a narrow
    vLLM-version limitation, not a schema-correctness issue.
    """
    defs = schema.get("$defs", {})
    if not isinstance(defs, dict):
        return schema

    def resolve(node: object) -> object:
        if isinstance(node, dict):
            if "$ref" in node:
                ref = str(node["$ref"]).removeprefix("#/$defs/")
                return resolve(defs[ref])
            return {k: resolve(v) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [resolve(item) for item in node]
        return node

    result = resolve(schema)
    assert isinstance(result, dict)
    return result


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


class LLMRouterConfig(BaseModel):
    tiers: list[TierConfig]
    # Empty by default -- TierConfig.timeout_s is the single source of
    # truth for a tier's timeout unless a caller explicitly wants to
    # override it per-router-instance via this dict. Previously this
    # defaulted to a second, independently-hardcoded timeout table
    # (DEFAULT_TIMEOUT_BY_TIER: tier1=60s) that silently won over
    # whatever a caller set on TierConfig.timeout_s -- confirmed live:
    # raising a TierConfig's timeout_s to 240s had NO effect, a real S41
    # call kept timing out at 60s regardless, because complete() prefers
    # timeout_by_tier over tier.timeout_s and this dict was never empty.
    # That drift is exactly what this collapses (docs/gaps.md #33a).
    timeout_by_tier: dict[LLMTier, int] = Field(default_factory=dict)


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


TierTransport = Callable[
    [TierConfig, list[dict[str, str]], int, "dict[str, object] | None"], Awaitable[LLMResponse]
]


async def default_http_transport(
    tier: TierConfig,
    messages: list[dict[str, str]],
    timeout_s: int,
    schema: dict[str, object] | None = None,
) -> LLMResponse:
    """Real OpenAI-compatible transport used against vllm/llama.cpp/hosted APIs.

    `schema`, when given, is forwarded as `guided_json` -- vLLM's OpenAI-
    compatible extension for constrained/grammar-guided decoding (ADR-007).
    Previously `complete()` accepted a `schema` parameter but never actually
    used it anywhere in the call chain -- confirmed live: real relevance-
    filter/note-synthesis calls were producing malformed JSON (missing
    fields, over-length strings) that the small quantized Tier-1 model
    should never have been able to emit if constrained decoding were
    actually active. This wires it through. Hosted-API tiers (3/4) don't
    support `guided_json`, so this is a best-effort hint, not a contract --
    a tier that ignores it just behaves as it did before.
    """
    start = time.monotonic()
    request_body: dict[str, object] = {"model": tier.model, "messages": messages}
    if schema is not None:
        request_body["guided_json"] = schema
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.post(
                f"{tier.endpoint.rstrip('/')}/chat/completions",
                json=request_body,
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
                response = await self._try_tier(tier, messages, timeout_s, schema)
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
        self,
        tier: TierConfig,
        messages: list[dict[str, str]],
        timeout: int,
        schema: dict[str, object] | None,
    ) -> LLMResponse:
        return await self._transport(tier, messages, timeout, schema)
