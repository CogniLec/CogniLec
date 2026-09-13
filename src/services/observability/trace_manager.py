"""S39 — Trace propagation, cost attribution, and agent-isolation assertion.

LangFuse is the target backend (see config/langfuse.yaml + docker-compose), but
none of the logic here depends on LangFuse being reachable: `TraceManager`
writes `agent_runs` rows through a pluggable sink and LangFuse ingestion is a
best-effort side channel, per the "buffer locally, flush on reconnect" fallback
in the S39 spec.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from contextvars import ContextVar
from datetime import UTC, datetime

from src.services.observability.models import AgentRun

trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")
session_id_var: ContextVar[str] = ContextVar("session_id", default="")

AgentRunSink = Callable[[AgentRun], None]

# Isolation rule (AC-15 precursor): A3 (Socratic Guide) and A5 (Exam Sim) must
# never invoke one another directly within the same trace.
ISOLATED_AGENT_PAIRS: frozenset[frozenset[str]] = frozenset({frozenset({"A3", "A5"})})


class TraceManager:
    def __init__(self, sink: AgentRunSink | None = None) -> None:
        self._sink = sink
        self._runs: list[AgentRun] = []

    def start_trace(self, session_id: str) -> str:
        trace_id = str(uuid.uuid4())
        trace_id_var.set(trace_id)
        session_id_var.set(session_id)
        return trace_id

    def start_span(self, name: str, attributes: dict[str, object]) -> str:
        return str(uuid.uuid4())

    def end_span(self, span_id: str, attributes: dict[str, object] | None = None) -> None:
        return None

    def record_agent_run(self, run: AgentRun) -> None:
        self._runs.append(run)
        if self._sink is not None:
            self._sink(run)

    @property
    def runs(self) -> list[AgentRun]:
        return list(self._runs)


def redact_for_trace(payload: dict[str, object], allowed_keys: set[str]) -> dict[str, object]:
    """Strip raw transcript/free-text content from a payload before it reaches a trace.

    NFR-S10: traces may carry metadata (token counts, latency, tier) but never raw
    student conversation content.
    """
    return {k: v for k, v in payload.items() if k in allowed_keys}


def compute_session_cost(runs: list[AgentRun], session_id: str) -> dict[str, float | int | str]:
    matching = [r for r in runs if r.session_id == session_id]
    total_cost = sum(r.cost_usd for r in matching)
    total_input = sum(r.input_tokens for r in matching)
    total_output = sum(r.output_tokens for r in matching)
    return {
        "session_id": session_id,
        "total_cost_usd": round(total_cost, 6),
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_agent_calls": len(matching),
    }


def find_agent_isolation_violations(runs: list[AgentRun]) -> list[tuple[str, str]]:
    """Python equivalent of the agent-isolation SQL assertion in the S39 spec.

    Two runs violate isolation when they share a trace_id + session_id, one
    completes at or before the other starts (i.e. a hand-off edge exists), and
    the agent pair is in ISOLATED_AGENT_PAIRS (currently {A3, A5}).
    """
    violations: list[tuple[str, str]] = []
    by_trace: dict[tuple[str, str], list[AgentRun]] = {}
    for run in runs:
        by_trace.setdefault((run.trace_id, run.session_id), []).append(run)

    for grouped in by_trace.values():
        for r1 in grouped:
            for r2 in grouped:
                if r1 is r2 or r1.completed_at is None:
                    continue
                if r1.completed_at > r2.started_at:
                    continue
                pair = frozenset({r1.agent_id, r2.agent_id})
                if pair in ISOLATED_AGENT_PAIRS and r1.agent_id != r2.agent_id:
                    violations.append((r1.agent_id, r2.agent_id))
    return violations


def new_agent_run(
    session_id: str,
    trace_id: str,
    agent_id: str,
    model: str,
    tier: str,
    prompt_version: str,
    status: str = "started",
) -> AgentRun:
    from src.services.observability.models import AgentRunStatus

    return AgentRun(
        id=str(uuid.uuid4()),
        session_id=session_id,
        trace_id=trace_id,
        agent_id=agent_id,
        model=model,
        tier=tier,
        prompt_version=prompt_version,
        status=AgentRunStatus(status),
        started_at=datetime.now(UTC),
    )
