"""Tests for S74 - GPU Scheduling & Training Isolation.

============================================================================
HONESTY STATEMENT
============================================================================
Every test in this stage needs a real fine-tuning job actually contending
for GPU memory/cycles against a real live-serving workload (T74.1, T74.3,
T74.5), a real deployed image-gen worker with KEDA or equivalent scale-to-
zero (T74.2), or a full host reboot with a real service dependency graph
(T74.4, an S36 T36.2 regression - S36 was itself only ever verified against
this single dev machine, not a fleet). This sandbox has no GPU-loaded model
running at all (docs/gaps.md #2), so there is no live serving workload to
protect, no training job to schedule against it, and no MIG-capable
hardware to partition. There is nothing to honestly measure here beyond
"the binaries/configuration this stage would tune don't exist in this
environment" - every test below is a documented skip, not a fabricated
pass.
"""

from __future__ import annotations

import pytest


def test_t74_1_finetuning_does_not_degrade_asr_latency_not_available() -> None:
    pytest.skip(
        "No GPU-loaded ASR serving workload and no real fine-tuning job to contend with it "
        "(docs/gaps.md #2)"
    )


def test_t74_2_image_gen_scale_to_zero_not_available() -> None:
    pytest.skip("No KEDA/equivalent deployment and no image-gen worker to scale (docs/gaps.md #2)")


def test_t74_3_training_cannot_claim_reserved_gpu_memory_not_available() -> None:
    pytest.skip("No MIG-capable hardware or GPU scheduler configured in this sandbox")


def test_t74_4_service_start_order_after_reboot_not_available() -> None:
    pytest.skip(
        "T36.2 was only ever verified against this single dev machine, not a production fleet; "
        "re-running a full host reboot drill is outside this stage's scope on shared infra"
    )


def test_t74_5_idle_gpu_utilisation_drop_not_available() -> None:
    pytest.skip("No live GPU workload running in this sandbox to measure an idle drop against")
