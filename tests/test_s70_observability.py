"""Tests for S70 - Observability Stack.

============================================================================
HONESTY STATEMENT
============================================================================
The spec's stack (SigNoz/Grafana+Prometheus+Loki+Tempo, dcgm-exporter,
postgres-exporter, node-exporter, cAdvisor, GlitchTip, Uptime Kuma,
Alertmanager -> n8n) is a real multi-service cluster deployment this
sandbox cannot stand up: no outbound internet to pull the images, and no
GPU-visible dcgm-exporter target (docs/gaps.md - no GPU-loaded models, but
also no live GPU workload to scrape metrics from at all in this
environment beyond bare `nvidia-smi`). T70.1-T70.4 and T70.6 (seven
dashboards render, GPU metrics match `nvidia-smi`, alert reaches n8n,
WER-proxy dashboard detects an injected regression, trace correlation
across API->Prefect->LangGraph->model service) are honest skips - none of
that infrastructure exists here to assert against.

T70.5 ("per-session cost queryable and matching agent_runs sums") is the
one piece of arithmetic a dashboard panel needs that doesn't require the
stack itself - `src/services/observability/cost.py` computes it directly
from `agent_runs` rows and is tested for real below, including the
"matches agent_runs sums" property (summing the per-row costs equals the
per-session total the function returns).
"""

from __future__ import annotations

import uuid

import pytest
from src.services.observability.cost import compute_run_cost, cost_per_session


def test_t70_5_cost_per_session_matches_agent_runs_sums() -> None:
    session_a = uuid.uuid4()
    session_b = uuid.uuid4()
    runs = [
        {
            "session_id": session_a,
            "model": "gpt-4o-mini",
            "input_tokens": 1000,
            "output_tokens": 500,
        },
        {
            "session_id": session_a,
            "model": "gpt-4o-mini",
            "input_tokens": 2000,
            "output_tokens": 100,
        },
        {
            "session_id": session_b,
            "model": "microsoft/Phi-3-mini-3.8B-4bit",
            "input_tokens": 5000,
            "output_tokens": 5000,
        },
    ]
    totals = cost_per_session(runs)

    manual_a = sum(
        compute_run_cost(r["model"], r["input_tokens"], r["output_tokens"])
        for r in runs
        if r["session_id"] == session_a
    )
    manual_b = sum(
        compute_run_cost(r["model"], r["input_tokens"], r["output_tokens"])
        for r in runs
        if r["session_id"] == session_b
    )
    assert totals[session_a] == pytest.approx(manual_a)
    assert totals[session_b] == pytest.approx(manual_b)
    assert totals[session_a] > 0
    assert totals[session_b] == 0.0, "self-hosted tiers are modelled at zero marginal cost"


def test_t70_5_unknown_model_costs_zero_not_fabricated() -> None:
    assert compute_run_cost("some-unlisted-model", 10_000, 10_000) == 0.0


def test_t70_1_seven_dashboards_not_available() -> None:
    pytest.skip("SigNoz/Grafana stack not deployed in this sandbox - no internet (docs/gaps.md)")


def test_t70_2_gpu_metrics_not_available() -> None:
    pytest.skip("No dcgm-exporter deployed and no live GPU workload to scrape (docs/gaps.md #2)")


def test_t70_3_alert_reaches_n8n_not_available() -> None:
    pytest.skip("Alertmanager not deployed in this sandbox")


def test_t70_4_wer_proxy_regression_detection_not_available() -> None:
    pytest.skip("WER-proxy dashboard not deployed; no observability stack in this sandbox")


def test_t70_6_trace_correlation_not_available() -> None:
    pytest.skip("No LangFuse/Tempo backend reachable in this sandbox to assert span correlation")
