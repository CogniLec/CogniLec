"""S40 — Lightweight golden-case regression runner.

promptfoo (Node.js CLI) is not installed/practical to stand up in this
environment (no Node toolchain available here, and running an external
process per test adds unrelated flakiness). This module is a documented
substitution: a small, dependency-free Python runner that reads the same
golden-case JSONL format described in the S40 spec's promptfoo config and
applies `contains` / `javascript`-equivalent assertions against a completion
function. CI wires this the same way it would wire `promptfoo eval`: it fails
the build on any regression.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from src.services.prompts.models import RegressionResult

CompletionFn = Callable[[dict[str, Any]], dict[str, Any]]


def load_golden_cases(path: Path) -> list[dict[str, Any]]:
    cases = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            cases.append(json.loads(line))
    return cases


def _check_assertion(assertion: dict[str, Any], output: dict[str, Any]) -> bool:
    kind = assertion["type"]
    if kind == "contains":
        haystack = json.dumps(output).lower()
        return assertion["value"].lower() in haystack
    if kind == "field_equals":
        return bool(output.get(assertion["field"]) == assertion["value"])
    if kind == "field_min_length":
        value = output.get(assertion["field"])
        return isinstance(value, list) and len(value) >= assertion["value"]
    msg = f"unsupported assertion type: {kind}"
    raise ValueError(msg)


def run_regression_suite(
    agent_id: str,
    prompt_version: str,
    golden_cases: list[dict[str, Any]],
    completion_fn: CompletionFn,
) -> RegressionResult:
    passed = 0
    failed_cases: list[dict[str, Any]] = []

    for case in golden_cases:
        output = completion_fn(case["vars"])
        ok = all(_check_assertion(a, output) for a in case.get("assert", []))
        if ok:
            passed += 1
        else:
            failed_cases.append({"vars": case["vars"], "output": output})

    total = len(golden_cases)
    return RegressionResult(
        agent_id=agent_id,
        prompt_version=prompt_version,
        total_cases=total,
        passed=passed,
        failed=total - passed,
        pass_rate=(passed / total) if total else 0.0,
        failed_cases=failed_cases or None,
    )
