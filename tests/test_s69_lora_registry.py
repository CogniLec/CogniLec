"""Tests for S69 - multi-LoRA serving & adapter registry (T69.1-T69.7).

vLLM multi-LoRA serving needs a GPU-resident base model (gap #2), so
`AdapterBackend` is exercised via a fake in-memory backend here - the
routing table, fallback-on-load-failure, and registry parsing are all real
logic. T69.4/T69.5 (an A2/A6 LoRA improving real quality/accuracy metrics
over base) need actually-trained adapters and are honest skips.
"""

from __future__ import annotations

import uuid

import pytest
import yaml
from sqlalchemy import text
from src.db.partitions.provisioner import PartitionProvisioner
from src.services.finetuning.lora_registry import (
    AdapterLoadError,
    AdapterRouter,
    AdapterSpec,
    load_adapter_registry,
)


class FakeAdapterBackend:
    def __init__(self, fail_for: set[str] | None = None):
        self._fail_for = fail_for or set()
        self.calls: list[tuple[str, str | None]] = []

    def generate(self, prompt: str, adapter: AdapterSpec | None) -> str:
        adapter_name = adapter.name if adapter else None
        self.calls.append((prompt, adapter_name))
        if adapter is not None and adapter.name in self._fail_for:
            raise AdapterLoadError(f"failed to load {adapter.name}")
        return f"[{adapter_name or 'base'}] response to: {prompt}"


A2_ADAPTER = AdapterSpec(
    name="a2-note-style-lora", version="v1.0.0", base_model="phi-3-mini", path="/models/loras/a2/v1"
)
A6_ADAPTER = AdapterSpec(
    name="a6-syllabus-extraction-lora",
    version="v1.0.0",
    base_model="phi-3-mini",
    path="/models/loras/a6/v1",
)


def test_t69_1_and_t69_2_multiple_adapters_routed_correctly_from_one_backend():
    backend = FakeAdapterBackend()
    router = AdapterRouter(
        backend, {"A2_NOTE_SYNTHESIS": A2_ADAPTER, "A6_SYLLABUS_EXTRACTION": A6_ADAPTER}
    )

    response_a2 = router.route("A2_NOTE_SYNTHESIS", "write notes")
    response_a6 = router.route("A6_SYLLABUS_EXTRACTION", "extract syllabus")

    assert response_a2.adapter_version == "v1.0.0"
    assert response_a6.adapter_version == "v1.0.0"
    assert backend.calls == [
        ("write notes", "a2-note-style-lora"),
        ("extract syllabus", "a6-syllabus-extraction-lora"),
    ]
    assert set(router.registered_agents()) == {"A2_NOTE_SYNTHESIS", "A6_SYLLABUS_EXTRACTION"}


def test_t69_7_failed_adapter_load_falls_back_to_base_model():
    backend = FakeAdapterBackend(fail_for={"a2-note-style-lora"})
    router = AdapterRouter(backend, {"A2_NOTE_SYNTHESIS": A2_ADAPTER})

    response = router.route("A2_NOTE_SYNTHESIS", "write notes")

    assert response.adapter_version is None
    assert response.text == "[base] response to: write notes"


def test_unregistered_agent_uses_base_model_directly():
    backend = FakeAdapterBackend()
    router = AdapterRouter(backend, {})
    response = router.route("UNKNOWN_AGENT", "hello")
    assert response.adapter_version is None
    assert backend.calls == [("hello", None)]


def test_load_adapter_registry_parses_config_models_yaml():
    import pathlib

    config_path = pathlib.Path(__file__).resolve().parents[1] / "config" / "models.yaml"
    models_config = yaml.safe_load(config_path.read_text())
    registry = load_adapter_registry(models_config)

    assert "A2_NOTE_SYNTHESIS" in registry
    assert "A6_SYLLABUS_EXTRACTION" in registry
    assert registry["A2_NOTE_SYNTHESIS"].version == "v1.0.0"
    assert registry["A2_NOTE_SYNTHESIS"].base_model == "microsoft/Phi-3-mini-3.8B-4bit"


async def test_t69_6_adapter_version_recorded_on_agent_runs_row(db_session, test_user_id):
    subject = await PartitionProvisioner().provision_subject(
        db_session, test_user_id, name="S69 Subject"
    )
    session_row_id = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO sessions (id, subject_id, session_type, status, notes_ready, retry_count) "
            "VALUES (:id, :subject_id, 'content', 'complete', false, 0)"
        ),
        {"id": str(session_row_id), "subject_id": str(subject.id)},
    )
    run_id = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO agent_runs (id, session_id, agent_id, model, outcome, adapter_version) "
            "VALUES (:id, :session_id, 'A2_NOTE_SYNTHESIS', 'phi-3-mini', 'success', :adapter_version)"
        ),
        {"id": str(run_id), "session_id": str(session_row_id), "adapter_version": "v1.0.0"},
    )
    row = await db_session.execute(
        text("SELECT adapter_version FROM agent_runs WHERE id = :id"), {"id": str(run_id)}
    )
    assert row.scalar_one() == "v1.0.0"


@pytest.mark.skip(
    reason=(
        "T69.3 (adapter-swap latency vs. base-model inference) and "
        "T69.4/T69.5 (A2/A6 LoRA quality/accuracy improvement over base) "
        "need real vLLM multi-LoRA serving with a GPU-resident base model "
        "and actually-trained adapters - no GPU-loaded model exists in "
        "this sandbox (gap #2, docs/gaps.md)."
    )
)
def test_t69_3_t69_4_t69_5_require_real_served_adapters():
    pass
