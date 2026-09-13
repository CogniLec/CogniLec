"""Per-stage GPU pinning config/wiring tests (docs/gaps.md gap #21).

This host has exactly one physical GPU (an NVIDIA T1000, 4GB VRAM - see
gap #15/#17/#20), so genuine multi-GPU concurrent execution cannot be
exercised here. These tests verify what CAN be verified without extra
hardware: that the new per-stage device settings exist with sane
single-GPU defaults, are correctly threaded into the ASR/embedding call
sites, and that the default (device 0, matching this host's real GPU)
behaves exactly as before the change - a regression check against the
device-selection mechanism gap #15/#17 already verified end to end.

Genuinely running 3 sessions concurrently on 3 different physical cards and
measuring a wall-clock speedup is out of reach in this sandbox and is
honestly skipped below, matching this repo's established pattern (compare
tests/test_s29_segmentation_gate.py's honest skips).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import yaml
from src.core.config import Settings
from src.services.asr.service import FasterWhisperASRService

COMPOSE_PATH = Path(__file__).parent.parent / "docker-compose.yml"


def test_gpu_settings_default_to_device_zero() -> None:
    """Single-GPU dev machines (this host included) get everything on device 0."""
    settings = Settings()
    assert settings.ASR_CUDA_DEVICE == 0
    assert settings.EMBEDDING_CUDA_DEVICE == 0
    assert settings.VLLM_GPU_DEVICE == "0"
    assert settings.DIARISATION_GPU_DEVICE == "0"


def test_gpu_settings_overridable_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 3-GPU deployment pins each stage independently via env vars."""
    monkeypatch.setenv("ASR_CUDA_DEVICE", "1")
    monkeypatch.setenv("EMBEDDING_CUDA_DEVICE", "2")
    monkeypatch.setenv("VLLM_GPU_DEVICE", "1")
    monkeypatch.setenv("DIARISATION_GPU_DEVICE", "2")
    settings = Settings()
    assert settings.ASR_CUDA_DEVICE == 1
    assert settings.EMBEDDING_CUDA_DEVICE == 2
    assert settings.VLLM_GPU_DEVICE == "1"
    assert settings.DIARISATION_GPU_DEVICE == "2"


def test_asr_service_passes_device_index_to_whisper_model() -> None:
    """FasterWhisperASRService must forward device_index to WhisperModel, not just device."""
    with patch("faster_whisper.WhisperModel") as mock_model:
        FasterWhisperASRService(
            model_name="tiny.en",
            compute_type="int8",
            device="cuda",
            beam_size=5,
            language="en",
            embed_model_ver="qwen3-0.6b-v1",
            device_index=2,
        )
    mock_model.assert_called_once_with(
        "tiny.en", device="cuda", device_index=2, compute_type="int8"
    )


def test_asr_service_device_index_defaults_to_zero() -> None:
    """Regression: omitting device_index (as all existing call sites used to) still means 0."""
    with patch("faster_whisper.WhisperModel") as mock_model:
        FasterWhisperASRService(
            model_name="tiny.en",
            compute_type="int8",
            device="cpu",
            beam_size=5,
            language="en",
            embed_model_ver="qwen3-0.6b-v1",
        )
    mock_model.assert_called_once_with("tiny.en", device="cpu", device_index=0, compute_type="int8")


def test_asr_worker_wires_settings_asr_cuda_device_into_service(monkeypatch: Any) -> None:
    """The worker's default ASR service construction must read ASR_CUDA_DEVICE."""
    from src.core.config import get_settings
    from src.workers.asr_worker import ASRWorker

    get_settings.cache_clear()
    monkeypatch.setenv("ASR_CUDA_DEVICE", "1")
    settings = get_settings()
    get_settings.cache_clear()

    captured: dict[str, object] = {}

    class _FakeASRService:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    with patch("src.workers.asr_worker.FasterWhisperASRService", _FakeASRService):
        ASRWorker(session_factory=lambda: None, settings=settings)

    assert captured["device_index"] == 1


def test_embedding_client_local_device_defaults_to_cpu() -> None:
    """Regression: the existing degraded-fallback default (CPU) is unchanged."""
    from src.ml.embedding.client import EmbeddingClient

    client = EmbeddingClient()
    assert client._local_device == "cpu"


def test_embedding_client_local_device_overridable() -> None:
    from src.ml.embedding.client import EmbeddingClient

    client = EmbeddingClient(local_device="cuda:2")
    assert client._local_device == "cuda:2"


def test_embedding_client_passes_local_device_to_model_loader() -> None:
    from src.ml.embedding.client import EmbeddingClient

    client = EmbeddingClient(local_device="cuda:1")
    with patch("src.ml.embedding.embed.load_embedding_model") as mock_load:
        client._embed_local(["hello"])
    assert mock_load.call_args.kwargs["device"] == "cuda:1"


def test_docker_compose_vllm_and_diarisation_gpu_device_configurable() -> None:
    """docker-compose.yml pins vllm/diarisation to a configurable device_ids list,
    not a hardcoded count, following the same reservation shape for both."""
    compose = yaml.safe_load(COMPOSE_PATH.read_text())
    for service_name, var_name in [
        ("vllm", "VLLM_GPU_DEVICE"),
        ("diarisation", "DIARISATION_GPU_DEVICE"),
    ]:
        service = compose["services"][service_name]
        devices = service["deploy"]["resources"]["reservations"]["devices"]
        assert len(devices) == 1
        device = devices[0]
        assert device["driver"] == "nvidia"
        assert device["capabilities"] == ["gpu"]
        assert device["device_ids"] == [f"${{{var_name}:-0}}"]


@pytest.mark.skip(
    reason=(
        "Requires 3 physical GPUs to verify genuinely: this host has one "
        "NVIDIA T1000 (see gap #15/#17/#20), so 3 sessions running "
        "concurrently on 3 different physical cards with a measured "
        "wall-clock speedup cannot be exercised here. The config/wiring "
        "this gap adds (ASR_CUDA_DEVICE/EMBEDDING_CUDA_DEVICE/"
        "VLLM_GPU_DEVICE/DIARISATION_GPU_DEVICE) is verified by the other "
        "tests in this module; only the real multi-card concurrency and "
        "throughput claim is unverified pending that hardware."
    )
)
def test_three_gpu_concurrent_sessions_speedup() -> None:
    raise NotImplementedError
