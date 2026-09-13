"""S06 Gate checking tests — offline, verifies logic with temp files."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from src.ml.gates import (
    ASR_WER_THRESHOLD,
    check_all_gates,
    check_asr_gate,
    check_config_frozen,
    check_embedding_gate,
)


@pytest.fixture
def tmp_docs(tmp_path: Path):
    """Create a temporary docs directory and set working dir."""
    docs = tmp_path / "docs"
    docs.mkdir()
    return docs


def _write_csv(path: Path, rows: list[dict]) -> None:
    """Write a list of dicts to a CSV file with headers."""
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


class TestCheckAsrGate:
    def test_passes_when_wer_low(self, tmp_docs: Path):
        csv_path = tmp_docs / "bakeoff-asr-results.csv"
        rows = [
            {
                "model": "whisper",
                "condition": "front_quiet",
                "wer": 0.12,
                "cer": 0.05,
                "rtf": 0.3,
                "vram_peak_mb": 3200,
                "quantization": "int8_float16",
                "compute_type": "int8_float16",
            },
            {
                "model": "whisper",
                "condition": "back_quiet",
                "wer": 0.15,
                "cer": 0.07,
                "rtf": 0.3,
                "vram_peak_mb": 3200,
                "quantization": "int8_float16",
                "compute_type": "int8_float16",
            },
        ]
        _write_csv(csv_path, rows)

        passed, details = check_asr_gate(csv_path)
        assert passed is True
        assert details["best_median_wer"] < ASR_WER_THRESHOLD

    def test_fails_when_wer_high(self, tmp_docs: Path):
        csv_path = tmp_docs / "bakeoff-asr-results.csv"
        rows = [
            {
                "model": "bad",
                "condition": "front_quiet",
                "wer": 0.40,
                "cer": 0.20,
                "rtf": 1.0,
                "vram_peak_mb": 4000,
                "quantization": "fp16",
                "compute_type": "fp16",
            },
        ]
        _write_csv(csv_path, rows)

        passed, _details = check_asr_gate(csv_path)
        assert passed is False

    def test_missing_file(self, tmp_docs: Path):
        passed, details = check_asr_gate(tmp_docs / "nonexistent.csv")
        assert passed is False
        assert "error" in details


class TestCheckEmbeddingGate:
    def test_passes_when_purity_high(self, tmp_docs: Path):
        csv_path = tmp_docs / "bakeoff-embedding-results.csv"
        rows = [
            {
                "model": "qwen3-0.6b",
                "dim": 1024,
                "purity": 0.75,
                "v_measure": 0.68,
                "silhouette": 0.12,
                "umap_n_neighbors": 15,
                "hdbscan_min_cluster_size": 5,
            },
        ]
        _write_csv(csv_path, rows)

        passed, _details = check_embedding_gate(csv_path)
        assert passed is True

    def test_fails_when_purity_low(self, tmp_docs: Path):
        csv_path = tmp_docs / "bakeoff-embedding-results.csv"
        rows = [
            {
                "model": "qwen3-0.6b",
                "dim": 1024,
                "purity": 0.50,
                "v_measure": 0.40,
                "silhouette": 0.05,
                "umap_n_neighbors": 15,
                "hdbscan_min_cluster_size": 5,
            },
        ]
        _write_csv(csv_path, rows)

        passed, _details = check_embedding_gate(csv_path)
        assert passed is False


class TestCheckConfigFrozen:
    def test_passes_with_all_keys(self, tmp_path: Path, monkeypatch):
        config = {
            "asr_model": "whisper-large-v3-turbo",
            "asr_model_revision": "main",
            "asr_compute_type": "fp16",
            "asr_device": "cuda",
            "asr_beam_size": 5,
            "asr_batch_size": 16,
            "embedding_model": "Qwen/Qwen3-Embedding-0.6B",
            "embedding_dim": 1024,
            "embedding_revision": "main",
            "embedding_device": "cuda",
            "embedding_batch_size": 32,
        }
        config_path = tmp_path / "models.yaml"
        import yaml

        with config_path.open("w") as f:
            yaml.dump(config, f)

        monkeypatch.setattr("src.ml.gates.CONFIG_PATH", config_path)
        passed, details = check_config_frozen()
        assert passed is True
        assert details["asr_model"] == "whisper-large-v3-turbo"

    def test_fails_when_missing_key(self, tmp_path: Path, monkeypatch):
        config = {"asr_model": "whisper", "embedding_model": "qwen3"}
        config_path = tmp_path / "models.yaml"
        import yaml

        with config_path.open("w") as f:
            yaml.dump(config, f)

        monkeypatch.setattr("src.ml.gates.CONFIG_PATH", config_path)
        passed, details = check_config_frozen()
        assert passed is False
        assert len(details["missing_keys"]) > 0

    def test_missing_file(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr("src.ml.gates.CONFIG_PATH", tmp_path / "nope.yaml")
        passed, _details = check_config_frozen()
        assert passed is False


class TestCheckAllGates:
    def test_returns_list(self):
        _passed, results = check_all_gates()
        assert isinstance(results, list)
        assert len(results) >= 3  # at least ASR, embedding, config
        for r in results:
            assert "gate" in r
            assert "passed" in r
