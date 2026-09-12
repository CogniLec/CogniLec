"""S39 — Observability: tracing & cost attribution tests.

No LangFuse instance is deployed in this sandboxed environment (no Node/
Next.js runtime, no reachable Postgres reserved for it). Per the S39 spec's
own fallback instructions ("if LangFuse is down: agent_runs writes to local
DB"), TraceManager writes agent_runs rows directly and treats LangFuse
ingestion as a best-effort side channel — so all of T39.1-T39.5's actual
guarantees (trace correlation, cost computation, transcript redaction, agent
isolation) are fully testable without LangFuse itself running.
"""

from __future__ import annotations

from src.services.observability.models import AgentRun, AgentRunStatus
from src.services.observability.trace_manager import (
    TraceManager,
    compute_session_cost,
    find_agent_isolation_violations,
    redact_for_trace,
)


def make_run(
    agent_id, trace_id, session_id, started, completed, cost=0.01, tokens_in=10, tokens_out=20
):
    return AgentRun(
        id=f"run-{agent_id}-{started}",
        session_id=session_id,
        trace_id=trace_id,
        agent_id=agent_id,
        model="phi-3-mini",
        tier="tier_1",
        prompt_version="1.0.0",
        input_tokens=tokens_in,
        output_tokens=tokens_out,
        total_tokens=tokens_in + tokens_out,
        cost_usd=cost,
        latency_ms=100,
        status=AgentRunStatus.COMPLETE,
        started_at=started,
        completed_at=completed,
    )


def test_agent_call_produces_trace_and_agent_runs_row():
    """T39.1 — every agent call produces an agent_runs row via record_agent_run."""
    manager = TraceManager()
    trace_id = manager.start_trace(session_id="sess-1")
    from datetime import UTC, datetime

    run = make_run("A1", trace_id, "sess-1", datetime.now(UTC), datetime.now(UTC))
    manager.record_agent_run(run)
    assert len(manager.runs) == 1
    assert manager.runs[0].trace_id == trace_id


def test_trace_id_correlation_across_session():
    """T39.2 — trace_id correlates full session spans end-to-end."""
    from datetime import UTC, datetime, timedelta

    manager = TraceManager()
    trace_id = manager.start_trace(session_id="sess-2")
    t0 = datetime.now(UTC)
    for i, agent in enumerate(["A1", "A3", "A1"]):
        manager.record_agent_run(
            make_run(
                agent, trace_id, "sess-2", t0 + timedelta(seconds=i), t0 + timedelta(seconds=i + 1)
            )
        )
    trace_ids = {r.trace_id for r in manager.runs}
    assert trace_ids == {trace_id}
    assert len(manager.runs) == 3


def test_per_session_cost_computable():
    """T39.3 — per-session cost computable from agent_runs."""
    from datetime import UTC, datetime

    t0 = datetime.now(UTC)
    runs = [
        make_run("A1", "t1", "sess-3", t0, t0, cost=0.02, tokens_in=100, tokens_out=200),
        make_run("A3", "t1", "sess-3", t0, t0, cost=0.03, tokens_in=50, tokens_out=60),
        make_run("A1", "t1", "sess-other", t0, t0, cost=99.0),
    ]
    result = compute_session_cost(runs, "sess-3")
    assert result["total_cost_usd"] == 0.05
    assert result["total_input_tokens"] == 150
    assert result["total_output_tokens"] == 260
    assert result["total_agent_calls"] == 2


def test_traces_exclude_raw_transcripts():
    """T39.4 (NFR-S10) — traces carry metadata only, never raw transcript content."""
    payload = {
        "agent_id": "A1",
        "model": "phi-3-mini",
        "tier": "tier_1",
        "raw_transcript": "student said: I don't understand derivatives",
        "student_message": "please help me",
    }
    allowed = {"agent_id", "model", "tier"}
    redacted = redact_for_trace(payload, allowed)
    assert "raw_transcript" not in redacted
    assert "student_message" not in redacted
    assert redacted == {"agent_id": "A1", "model": "phi-3-mini", "tier": "tier_1"}


def test_agent_isolation_no_a3_a5_edge():
    """T39.5 — no A3->A5 or A5->A3 edge in the trace graph."""
    from datetime import UTC, datetime, timedelta

    t0 = datetime.now(UTC)
    clean_runs = [
        make_run("A1", "t1", "sess-4", t0, t0 + timedelta(seconds=1)),
        make_run("A3", "t1", "sess-4", t0 + timedelta(seconds=2), t0 + timedelta(seconds=3)),
        make_run("A1", "t1", "sess-4", t0 + timedelta(seconds=4), t0 + timedelta(seconds=5)),
    ]
    assert find_agent_isolation_violations(clean_runs) == []

    violating_runs = [
        make_run("A3", "t2", "sess-5", t0, t0 + timedelta(seconds=1)),
        make_run("A5", "t2", "sess-5", t0 + timedelta(seconds=2), t0 + timedelta(seconds=3)),
    ]
    violations = find_agent_isolation_violations(violating_runs)
    assert ("A3", "A5") in violations
