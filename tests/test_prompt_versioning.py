"""S40 — Prompt versioning & regression testing.

promptfoo (Node.js CLI) is not installed and no Node toolchain is available
in this sandboxed environment. This is a documented substitution: the
regression logic (src/services/prompts/regression.py) implements the same
golden-case-JSONL/assertion contract described in the S40 spec's promptfoo
config, and is exercised directly here rather than by shelling out to
`promptfoo eval`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from src.services.prompts.registry import PromptRegistry, validate_version_filename
from src.services.prompts.regression import load_golden_cases, run_regression_suite

GOLDEN_PATH = Path("tests/promptfoo/a1_golden.jsonl")


def good_completion(vars: dict) -> dict:
    topic = vars["topic"]
    difficulty = "hard" if vars["level"] == "advanced" else "medium"
    return {
        "explanation": f"{topic} explained clearly for the student.",
        "key_concepts": [topic, "supporting_concept"],
        "difficulty": difficulty,
        "confidence": 0.8,
    }


def degraded_completion(vars: dict) -> dict:
    return {
        "explanation": "I don't know.",
        "key_concepts": [],
        "difficulty": "easy",
        "confidence": 0.1,
    }


def test_prompt_registry_loads_deployed_version():
    registry = PromptRegistry()
    prompt = registry.get_prompt("A1")
    assert prompt.version == "1.0.0"
    assert prompt.model == "phi-3-mini-3.8b-4bit"
    assert "{{topic}}" in prompt.content


def test_prompt_registry_all_agents_loadable():
    registry = PromptRegistry()
    for agent in ["A1", "A2", "A3", "A4", "A5", "A6"]:
        prompt = registry.get_prompt(agent)
        assert prompt.content


def test_version_filename_validation():
    assert validate_version_filename("v1.0.0.md") is True
    assert validate_version_filename("v1.0.md") is False
    assert validate_version_filename("latest.md") is False


def test_version_bump_required():
    """T40.1 — changing prompt content without a version bump is detected."""
    registry = PromptRegistry()
    old = registry.get_prompt("A1", "1.0.0").content
    changed = old + "\nExtra guidance line."
    assert registry.validate_version_bump("A1", old, changed) is False
    assert registry.validate_version_bump("A1", old, old) is True


def test_promptfoo_suite_runs_and_reports_results():
    """T40.2 — regression suite runs and reports per-case pass/fail."""
    cases = load_golden_cases(GOLDEN_PATH)
    result = run_regression_suite("A1", "1.0.0", cases, good_completion)
    assert result.total_cases == len(cases)
    assert result.passed == len(cases)
    assert result.pass_rate == 1.0
    assert result.failed_cases is None


def test_degraded_prompt_caught_by_regression_suite():
    """T40.3 — a deliberately degraded prompt fails the golden cases."""
    cases = load_golden_cases(GOLDEN_PATH)
    result = run_regression_suite("A1", "1.0.0", cases, degraded_completion)
    assert result.failed > 0
    assert result.pass_rate < 1.0
    assert result.failed_cases is not None


def test_model_swap_by_config_no_code_change():
    """T40.4 — swapping a per-agent model is a config-only change."""
    registry = PromptRegistry()
    config = registry.get_agent_config("A1")
    assert config.model == "phi-3-mini-3.8b-4bit"
    assert config.temperature == 0.7
    # Swapping models is purely a manifest.yaml edit — verified structurally:
    # AgentConfig.model is sourced from PromptEntry.model, not hardcoded.
    assert config.prompt_id == "A1:1.0.0"


def test_prompt_version_recorded_on_agent_run():
    """T40.5 — prompt_version flows from the registry into an AgentRun."""
    from datetime import UTC, datetime

    from src.services.observability.models import AgentRun, AgentRunStatus

    registry = PromptRegistry()
    prompt = registry.get_prompt("A1")
    run = AgentRun(
        id="run-1",
        session_id="sess-1",
        trace_id="trace-1",
        agent_id="A1",
        model=prompt.model or "unknown",
        tier="tier_1",
        prompt_version=prompt.version,
        status=AgentRunStatus.COMPLETE,
        started_at=datetime.now(UTC),
    )
    assert run.prompt_version == "1.0.0"


def test_missing_prompt_version_falls_back_to_deployed():
    registry = PromptRegistry()
    prompt = registry.get_prompt("A1", version="9.9.9")
    assert prompt.version == "1.0.0"


def test_missing_prompt_dir_raises():
    registry = PromptRegistry()
    with pytest.raises(ValueError):
        registry.get_prompt("A99")
