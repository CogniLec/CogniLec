"""S25 — embedding model version registry (`config/models.yaml` → embedding_versions)."""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

MODELS_YAML_PATH = Path(__file__).resolve().parents[3] / "config" / "models.yaml"


class ModelVersionInfo(BaseModel):
    key: str
    model: str
    dim: int
    status: Literal["active", "deprecated", "backfilling"]
    instruction_prefix_retrieval: str
    instruction_prefix_clustering: str


class DimensionError(ValueError):
    """Raised when an embedding vector does not match the registered dimension."""


@functools.lru_cache(maxsize=1)
def _load_registry(path: Path = MODELS_YAML_PATH) -> dict[str, object]:
    with path.open() as f:
        config: dict[str, object] = yaml.safe_load(f)
    registry = config.get("embedding_versions", {})
    return dict(registry) if isinstance(registry, dict) else {}


def get_active_version(path: Path = MODELS_YAML_PATH) -> ModelVersionInfo:
    """Read the active embedding model version from `config/models.yaml`."""
    registry = _load_registry(path)
    active_key = str(registry["active"])
    return get_version(active_key, path)


def get_version(key: str, path: Path = MODELS_YAML_PATH) -> ModelVersionInfo:
    """Look up a specific embedding model version by key."""
    registry = _load_registry(path)
    versions = registry["registry"]
    assert isinstance(versions, dict)
    entry = versions[key]
    return ModelVersionInfo(
        key=key,
        model=entry["model"],
        dim=entry["dim"],
        status=entry["status"],
        instruction_prefix_retrieval=entry["instruction_prefix_retrieval"],
        instruction_prefix_clustering=entry["instruction_prefix_clustering"],
    )


def stamp_version(embedding_row: dict[str, object], version: str) -> dict[str, object]:
    """Set embed_model_ver on a row dict before insert."""
    embedding_row["embed_model_ver"] = version
    return embedding_row


def clear_cache() -> None:
    """Clear the cached registry (for tests that swap `config/models.yaml`)."""
    _load_registry.cache_clear()
