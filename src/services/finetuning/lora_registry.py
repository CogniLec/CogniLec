"""S69 — multi-LoRA serving & adapter registry.

vLLM multi-LoRA serving needs a GPU-resident base model (gap #2), so
`AdapterRouter` here is the real routing/fallback/registry logic wired
against an injectable backend - the same pattern as S36's `LLMRouter`
tiers. `config/models.yaml`'s `adapters` section is the registry: agent ID
-> adapter name -> version, with a `base_model` each adapter is trained
against.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class AdapterSpec:
    name: str
    version: str
    base_model: str
    path: str


class AdapterBackend(Protocol):
    def generate(self, prompt: str, adapter: AdapterSpec | None) -> str:
        """Run inference with `adapter` loaded (or base-model-only if None)."""
        ...


class AdapterLoadError(Exception):
    """Raised by a backend when an adapter fails to load."""


@dataclass(frozen=True)
class RoutedResponse:
    text: str
    adapter_version: str | None  # None means base-model fallback was used


class AdapterRouter:
    """Routes each agent to its registered adapter; falls back to base model on load failure.

    T69.2: routing is per-agent, never ambiguous - `registry` is a straight
    dict lookup. T69.7: a failed adapter load degrades to the base model
    rather than failing the request.
    """

    def __init__(self, backend: AdapterBackend, registry: dict[str, AdapterSpec]) -> None:
        self._backend = backend
        self._registry = registry

    def registered_agents(self) -> list[str]:
        return list(self._registry)

    def route(self, agent_id: str, prompt: str) -> RoutedResponse:
        adapter = self._registry.get(agent_id)
        if adapter is None:
            return RoutedResponse(text=self._backend.generate(prompt, None), adapter_version=None)
        try:
            text = self._backend.generate(prompt, adapter)
        except AdapterLoadError:
            return RoutedResponse(text=self._backend.generate(prompt, None), adapter_version=None)
        return RoutedResponse(text=text, adapter_version=adapter.version)


def load_adapter_registry(models_config: dict[str, Any]) -> dict[str, AdapterSpec]:
    """Parse `config/models.yaml`'s `adapters` section into an agent -> AdapterSpec map."""
    raw = models_config.get("adapters", {})
    registry: dict[str, AdapterSpec] = {}
    for agent_id, spec in raw.items():
        registry[agent_id] = AdapterSpec(
            name=spec["name"],
            version=spec["version"],
            base_model=spec["base_model"],
            path=spec["path"],
        )
    return registry
