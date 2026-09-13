"""S06 Configuration and model spec tests — offline, validates structure."""

from __future__ import annotations

from pathlib import Path

import yaml

CONFIG_PATH = Path("config/models.yaml")


class TestModelsYaml:
    def test_file_exists(self):
        assert CONFIG_PATH.exists(), f"config/models.yaml not found at {CONFIG_PATH}"

    def test_valid_yaml(self):
        with open(CONFIG_PATH) as f:
            config = yaml.safe_load(f)
        assert isinstance(config, dict)

    def test_asr_keys_present(self):
        with open(CONFIG_PATH) as f:
            config = yaml.safe_load(f)
        assert "asr_model" in config
        assert "asr_compute_type" in config
        assert "asr_device" in config
        assert "asr_beam_size" in config
        assert "asr_batch_size" in config

    def test_embedding_keys_present(self):
        with open(CONFIG_PATH) as f:
            config = yaml.safe_load(f)
        assert "embedding_model" in config
        assert "embedding_dim" in config
        assert "embedding_device" in config
        assert "embedding_batch_size" in config

    def test_asr_model_value(self):
        with open(CONFIG_PATH) as f:
            config = yaml.safe_load(f)
        # Should be one of the 4 evaluated models
        valid_asr = {
            "whisper-large-v3",
            "whisper-large-v3-turbo",
            "canary-qwen-2.5b",
            "parakeet-tdt-1.1b",
        }
        assert config["asr_model"] in valid_asr, f"Invalid asr_model: {config['asr_model']}"

    def test_embedding_dim_is_int(self):
        with open(CONFIG_PATH) as f:
            config = yaml.safe_load(f)
        assert isinstance(config["embedding_dim"], int)
        assert config["embedding_dim"] > 0

    def test_batch_sizes_positive(self):
        with open(CONFIG_PATH) as f:
            config = yaml.safe_load(f)
        assert config["asr_batch_size"] > 0
        assert config["embedding_batch_size"] > 0
