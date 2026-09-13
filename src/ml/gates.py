"""S06 Gate Checking — verifies bake-off results meet production thresholds."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

CONFIG_PATH = Path("config/models.yaml")

# Gate thresholds
ASR_WER_THRESHOLD = 0.20  # T06.1: best median WER < 20%
EMBEDDING_PURITY_THRESHOLD = 0.60  # T06.2: purity > 0.60
WORST_WER_WARNING = 0.35  # T06.3: warn if > 35%


def check_asr_gate(asr_results_path: Path | None = None) -> tuple[bool, dict[str, object]]:
    """Gate T06.1: Best ASR WER < 20% on median condition.

    Args:
        asr_results_path: path to bakeoff-asr-results.csv (or None to skip)

    Returns:
        (passed, details_dict)
    """
    if asr_results_path is None:
        asr_results_path = Path("docs/bakeoff-asr-results.csv")

    if not asr_results_path.exists():
        log.warning("No ASR results at %s — gate cannot be checked", asr_results_path)
        return False, {"error": "missing_results_file"}

    import pandas as pd

    df = pd.read_csv(asr_results_path)
    median_wers = df.groupby("condition")["wer"].median()
    best_median_wer = float(median_wers.min())
    passed = best_median_wer < ASR_WER_THRESHOLD

    details = {
        "best_median_wer": best_median_wer,
        "threshold": ASR_WER_THRESHOLD,
        "per_condition": median_wers.to_dict(),
    }
    return passed, details


def check_embedding_gate(emb_results_path: Path | None = None) -> tuple[bool, dict[str, object]]:
    """Gate T06.2: Clustering purity > 0.60.

    Args:
        emb_results_path: path to bakeoff-embedding-results.csv (or None to skip)

    Returns:
        (passed, details_dict)
    """
    if emb_results_path is None:
        emb_results_path = Path("docs/bakeoff-embedding-results.csv")

    if not emb_results_path.exists():
        log.warning("No embedding results at %s — gate cannot be checked", emb_results_path)
        return False, {"error": "missing_results_file"}

    import pandas as pd

    df = pd.read_csv(emb_results_path)
    best_purity = float(df["purity"].max())
    passed = best_purity > EMBEDDING_PURITY_THRESHOLD

    details: dict[str, object] = {
        "best_purity": best_purity,
        "threshold": EMBEDDING_PURITY_THRESHOLD,
    }
    return passed, details


def check_config_frozen() -> tuple[bool, dict[str, object]]:
    """T06.5: Verify config/models.yaml has all required keys."""
    if not CONFIG_PATH.exists():
        return False, {"error": "config_missing"}

    with CONFIG_PATH.open() as f:
        config = yaml.safe_load(f)

    required = [
        "asr_model",
        "asr_model_revision",
        "asr_compute_type",
        "asr_device",
        "asr_beam_size",
        "asr_batch_size",
        "embedding_model",
        "embedding_dim",
        "embedding_revision",
        "embedding_device",
        "embedding_batch_size",
    ]
    missing = [k for k in required if k not in config]
    passed = len(missing) == 0

    details = {
        "config_keys": list(config.keys()),
        "missing_keys": missing,
        "asr_model": config.get("asr_model"),
        "embedding_model": config.get("embedding_model"),
    }
    return passed, details


def check_all_gates() -> tuple[bool, list[dict[str, object]]]:
    """Run all S06 gate checks.

    Returns:
        (all_passed, list of per-gate result dicts)
    """
    results = []

    asr_passed, asr_details = check_asr_gate()
    results.append({"gate": "T06.1", "name": "ASR WER < 20%", "passed": asr_passed, **asr_details})

    emb_passed, emb_details = check_embedding_gate()
    results.append({"gate": "T06.2", "name": "Purity > 0.60", "passed": emb_passed, **emb_details})

    cfg_passed, cfg_details = check_config_frozen()
    results.append({"gate": "T06.5", "name": "Config frozen", "passed": cfg_passed, **cfg_details})

    all_passed = all(r["passed"] for r in results)
    return all_passed, results
