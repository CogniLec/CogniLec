"""S38 — Output validation: grammar-guaranteed for local tiers, bounded retry for hosted."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from src.services.llm.router import LLMTier
from src.services.llm.schema_registry import AgentID, SchemaRegistry, ValidationFailure

logger = logging.getLogger(__name__)

LOCAL_TIERS = {LLMTier.TIER_1, LLMTier.TIER_2}

# Retry callback: given the agent_id, prior raw output and error, produce a corrected raw output.
RetryFn = Callable[[AgentID, str, str], Awaitable[str]]


class SchemaValidationError(Exception):
    """Raised when hosted-tier output fails schema validation after the bounded retry."""


class OutputValidator:
    def __init__(
        self,
        registry: SchemaRegistry,
        retry_fn: RetryFn | None = None,
        max_retries: int = 1,
    ) -> None:
        self._registry = registry
        self._retry_fn = retry_fn
        self._max_retries = max_retries

    async def validate(
        self,
        agent_id: AgentID,
        raw_output: str,
        tier: LLMTier,
    ) -> dict[str, object]:
        """Validate output.

        Local tiers (TIER_1/TIER_2) are grammar-constrained upstream (Outlines/XGrammar),
        so validation here is a defensive assertion, not a retry loop — a failure at that
        point indicates the grammar contract itself broke and should alert, not retry.
        Hosted tiers get exactly one Instructor-style bounded retry before failing.
        """
        if tier in LOCAL_TIERS:
            return self._validate_local(agent_id, raw_output, tier)
        return await self._validate_hosted(agent_id, raw_output, tier)

    def _validate_local(
        self, agent_id: AgentID, raw_output: str, tier: LLMTier
    ) -> dict[str, object]:
        try:
            return self._registry.validate_output(agent_id, raw_output)
        except (json.JSONDecodeError, ValueError) as exc:
            self._log_failure(agent_id, raw_output, str(exc), tier, attempt=1)
            msg = (
                f"grammar-constrained local output for {agent_id} failed validation "
                "unexpectedly — this should be structurally impossible, alert immediately"
            )
            raise SchemaValidationError(msg) from exc

    async def _validate_hosted(
        self, agent_id: AgentID, raw_output: str, tier: LLMTier
    ) -> dict[str, object]:
        try:
            return self._registry.validate_output(agent_id, raw_output)
        except (json.JSONDecodeError, ValueError) as exc:
            self._log_failure(agent_id, raw_output, str(exc), tier, attempt=1)

        if self._retry_fn is None:
            msg = f"{agent_id} output invalid, no retry configured"
            raise SchemaValidationError(msg)

        for attempt in range(2, self._max_retries + 2):
            retried = await self._retry_fn(agent_id, raw_output, "schema validation failed")
            try:
                return self._registry.validate_output(agent_id, retried)
            except (json.JSONDecodeError, ValueError) as exc:
                self._log_failure(agent_id, retried, str(exc), tier, attempt=attempt)
                raw_output = retried

        msg = f"{agent_id} output invalid after {self._max_retries} bounded retry(ies) — failover"
        raise SchemaValidationError(msg)

    def _log_failure(
        self, agent_id: AgentID, raw_output: str, error: str, tier: LLMTier, attempt: int
    ) -> None:
        failure = ValidationFailure(
            agent_id=agent_id,
            raw_output=raw_output,
            error_message=error,
            tier=tier.value,
            attempt=attempt,
            timestamp=datetime.now(UTC).isoformat(),
        )
        logger.error(
            "schema validation failed",
            extra={"validation_failure": failure.model_dump()},
        )
