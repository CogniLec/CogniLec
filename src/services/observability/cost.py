"""S70 — per-session cost attribution against `agent_runs` (T70.5).

The seven-dashboard observability deployment itself (SigNoz/Grafana, the
exporters, alert routing) needs a real cluster to stand up in - see
`docs/gaps.md`'s S70 entry. What's real here is the one piece of that stack
that is pure computation over data already in Postgres: the cost-per-session
figure the "cost per session by agent" dashboard would plot. `config/
model_pricing.yaml` carries $/1K-token rates per model (0.0 for the two
self-hosted tiers); this module sums `agent_runs.input_tokens`/
`output_tokens` per row into a cost and rolls rows up per session and per
agent, so the arithmetic a dashboard panel would need is genuinely
tested against real `agent_runs` rows, independent of whether SigNoz itself
is deployed.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

import yaml

_PRICING_PATH = Path(__file__).resolve().parents[3] / "config" / "model_pricing.yaml"


@dataclass(frozen=True)
class AgentRunCost:
    agent_id: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


def _load_pricing() -> tuple[dict[str, float], dict[str, float]]:
    data = yaml.safe_load(_PRICING_PATH.read_text())
    return data["usd_per_1k_input_tokens"], data["usd_per_1k_output_tokens"]


def compute_run_cost(
    model: str,
    input_tokens: int | None,
    output_tokens: int | None,
    input_prices: dict[str, float] | None = None,
    output_prices: dict[str, float] | None = None,
) -> float:
    """Cost in USD for one agent_runs row. Unknown models cost 0.0 (not billed)."""
    if input_prices is None or output_prices is None:
        input_prices, output_prices = _load_pricing()
    in_rate = input_prices.get(model, 0.0)
    out_rate = output_prices.get(model, 0.0)
    return (input_tokens or 0) / 1000 * in_rate + (output_tokens or 0) / 1000 * out_rate


def cost_per_session(
    runs: list[dict[str, object]],
) -> dict[uuid.UUID, float]:
    """Sum per-row costs into a per-session total, given plain dict rows.

    Each row must carry `session_id`, `model`, `input_tokens`, `output_tokens`.
    """
    input_prices, output_prices = _load_pricing()
    totals: dict[uuid.UUID, float] = {}
    for row in runs:
        session_id = row["session_id"]
        assert isinstance(session_id, uuid.UUID)
        cost = compute_run_cost(
            str(row["model"]),
            row.get("input_tokens"),  # type: ignore[arg-type]
            row.get("output_tokens"),  # type: ignore[arg-type]
            input_prices,
            output_prices,
        )
        totals[session_id] = totals.get(session_id, 0.0) + cost
    return totals
