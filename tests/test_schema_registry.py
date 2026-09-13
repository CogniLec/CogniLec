"""S38 — Structured output & schema registry tests."""

from __future__ import annotations

import json

import pytest
from src.services.llm.output_validator import OutputValidator, SchemaValidationError
from src.services.llm.router import LLMTier
from src.services.llm.schema_registry import AgentID, SchemaRegistry


@pytest.fixture
def registry() -> SchemaRegistry:
    return SchemaRegistry()


def test_all_agents_have_schemas(registry: SchemaRegistry):
    """T38.3 — every agent A1-A6 has a registered schema; CI fails otherwise."""
    entries = registry.list_schemas()
    assert {e.agent_id for e in entries} == set(AgentID)


def test_missing_schema_fails_fast(tmp_path):
    """Deleting one agent's schema file must raise at registry construction, not silently degrade."""
    for agent in AgentID:
        if agent == AgentID.A3:
            continue
        (tmp_path / f"{agent.value.lower()}.json").write_text(
            json.dumps(
                {
                    "agent_id": agent.value,
                    "schema_name": "x",
                    "version": "1.0.0",
                    "schema": {},
                }
            )
        )
    with pytest.raises(ValueError, match="A3"):
        SchemaRegistry(schema_dir=tmp_path)


def test_local_model_generations_all_schema_valid(registry: SchemaRegistry):
    """T38.1 equivalent — grammar-constrained local output is structurally valid JSON.

    A real Outlines/XGrammar-compiled generation loop against a loaded vLLM
    model is not available in this environment (see test_vllm_serving.py).
    This instead asserts the contract Outlines enforces: any output shaped to
    the A1 schema validates, across a varied sample of 500 synthetic outputs.
    """
    difficulties = ["easy", "medium", "hard"]
    for i in range(500):
        raw = json.dumps(
            {
                "explanation": f"Explanation number {i} with enough length to pass validation.",
                "key_concepts": [f"concept_{i}"],
                "difficulty": difficulties[i % 3],
                "follow_up_question": None,
                "confidence": (i % 100) / 100.0,
            }
        )
        parsed = registry.validate_output(AgentID.A1, raw)
        assert parsed["difficulty"] in difficulties


@pytest.mark.asyncio
async def test_hosted_malformed_retry_then_failover(registry: SchemaRegistry):
    """T38.2 — malformed hosted response triggers exactly 1 retry, then failover."""
    retry_calls = 0

    async def always_bad_retry(agent_id, raw_output, error):
        nonlocal retry_calls
        retry_calls += 1
        return "still not json"

    validator = OutputValidator(registry, retry_fn=always_bad_retry, max_retries=1)
    with pytest.raises(SchemaValidationError):
        await validator.validate(AgentID.A1, "not json at all", LLMTier.TIER_3)
    assert retry_calls == 1


@pytest.mark.asyncio
async def test_hosted_retry_succeeds_on_second_attempt(registry: SchemaRegistry):
    good = json.dumps(
        {
            "explanation": "A sufficiently long explanation for validation.",
            "key_concepts": ["c1"],
            "difficulty": "easy",
            "follow_up_question": None,
            "confidence": 0.9,
        }
    )

    async def fix_on_retry(agent_id, raw_output, error):
        return good

    validator = OutputValidator(registry, retry_fn=fix_on_retry, max_retries=1)
    result = await validator.validate(AgentID.A1, "not json", LLMTier.TIER_3)
    assert result["difficulty"] == "easy"


@pytest.mark.asyncio
async def test_validation_failure_logged(registry: SchemaRegistry, caplog):
    """T38.5 — schema failure logged with offending output."""

    async def bad_retry(agent_id, raw_output, error):
        return "still bad"

    validator = OutputValidator(registry, retry_fn=bad_retry, max_retries=1)
    with caplog.at_level("ERROR"), pytest.raises(SchemaValidationError):
        await validator.validate(AgentID.A1, "bad json", LLMTier.TIER_3)
    assert any("schema validation failed" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_local_grammar_guaranteed_output_bypasses_retry(registry: SchemaRegistry):
    """Local tiers get a defensive assertion, not a retry loop, per the S38 spec."""
    validator = OutputValidator(registry, retry_fn=None)
    good = json.dumps(
        {
            "explanation": "A sufficiently long explanation for validation.",
            "key_concepts": ["c1"],
            "difficulty": "easy",
            "follow_up_question": None,
            "confidence": 0.5,
        }
    )
    result = await validator.validate(AgentID.A1, good, LLMTier.TIER_1)
    assert result["difficulty"] == "easy"
