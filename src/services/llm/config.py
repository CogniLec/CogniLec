"""S36 — Local LLM serving configuration (vLLM Tier 1)."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

DEFAULT_MODELS_YAML = Path("config/models.yaml")


class ModelTier(StrEnum):
    TIER_1 = "tier_1"


class VLLMConfig(BaseModel):
    model_name: str = "microsoft/Phi-3-mini-3.8B-4bit"
    model_path: str | None = None
    quantization: str = "awq"
    gpu_memory_utilization: float = Field(default=0.85, ge=0.1, le=1.0)
    max_model_len: int = 4096
    tensor_parallel_size: int = 1
    host: str = "0.0.0.0"
    port: int = 8000
    health_check_interval: int = 30
    max_concurrent: int = 4


class ModelInfo(BaseModel):
    name: str
    tier: ModelTier
    vram_required_gb: float
    quantization: str
    endpoint: str
    status: str = "idle"


class ModelsYamlConfig(BaseModel):
    """Typed view over the `tiers.tier_1` block of config/models.yaml."""

    model: str
    quantization: str
    vram_gb: float
    endpoint: str
    timeout_s: int
    gpu_required: bool


def load_vllm_tier_config(path: Path = DEFAULT_MODELS_YAML) -> ModelsYamlConfig:
    """Load and validate the Tier 1 (vLLM) entry from config/models.yaml.

    Raises FileNotFoundError / KeyError if the file or the tier_1 block is missing —
    this is a fail-fast startup dependency, not something to silently default.
    """
    raw: dict[str, Any] = yaml.safe_load(path.read_text())
    tier_1 = raw["tiers"]["tier_1"]
    return ModelsYamlConfig(**tier_1)


def assert_awq_quantization(model_metadata: dict[str, Any]) -> None:
    """Assert the loaded model reports AWQ quantization, not FP16.

    vLLM defaults to FP16 if --quantization is omitted; this guards against that
    silently co-opting the 4GB VRAM budget documented in S36.
    """
    quant = model_metadata.get("quantization")
    if quant != "awq":
        msg = f"expected AWQ quantization, got {quant!r} — refusing to serve FP16"
        raise ValueError(msg)
