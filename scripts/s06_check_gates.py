#!/usr/bin/env python3
"""S06 Gate Checker — Verifies bake-off results meet thresholds."""

import os
import sys

import mlflow
import pandas as pd

MLFLOW_URI = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")


def check_asr_gate():
    """Gate T06.1: Best ASR WER < 20% on median condition."""
    mlflow.set_tracking_uri(MLFLOW_URI)
    runs = mlflow.search_runs(experiment_names=["S06_ASR_Bakeoff"])
    if runs.empty:
        print("FAIL: No ASR bake-off runs found in MLflow")
        return False

    df = pd.DataFrame(runs)
    # Group by condition, get median WER per condition
    median_wers = df.groupby("params.condition")["metrics.wer"].median()
    best_median_wer = median_wers.min()

    print("ASR Median WERs per condition:")
    for cond, wer in median_wers.items():
        print(f"  {cond}: {wer:.1%}")
    print(f"Best median WER: {best_median_wer:.1%}")

    if best_median_wer < 0.20:
        print("PASS: Gate T06.1 (WER < 20%)")
        return True
    else:
        print("FAIL: Gate T06.1 (WER >= 20%) — PROJECT HALTS")
        return False


def check_embedding_gate():
    """Gate T06.2: Clustering purity > 0.60."""
    mlflow.set_tracking_uri(MLFLOW_URI)
    runs = mlflow.search_runs(experiment_names=["S06_Embedding_Bakeoff"])
    if runs.empty:
        print("FAIL: No embedding bake-off runs found in MLflow")
        return False

    df = pd.DataFrame(runs)
    best_purity = df["metrics.purity"].max()

    print("Embedding purity scores:")
    for _, row in df.iterrows():
        print(f"  dim={row.get('params.dim', 'N/A')}: purity={row['metrics.purity']:.3f}")
    print(f"Best purity: {best_purity:.3f}")

    if best_purity > 0.60:
        print("PASS: Gate T06.2 (purity > 0.60)")
        return True
    else:
        print("FAIL: Gate T06.2 (purity <= 0.60)")
        return False


def check_worst_condition():
    """T06.3: Worst condition WER recorded."""
    mlflow.set_tracking_uri(MLFLOW_URI)
    runs = mlflow.search_runs(experiment_names=["S06_ASR_Bakeoff"])
    if runs.empty:
        return False

    df = pd.DataFrame(runs)
    worst = df.loc[df["metrics.wer"].idxmax()]
    print(f"Worst condition: {worst['params.condition']} WER={worst['metrics.wer']:.1%}")

    if worst["metrics.wer"] > 0.35:
        print("WARNING: Worst condition WER > 35% — escalate as capture problem")
    return True


def check_disagreement():
    """T06.4: Pairwise disagreement analysis."""
    mlflow.set_tracking_uri(MLFLOW_URI)
    runs = mlflow.search_runs(experiment_names=["S06_Disagreement_Analysis"])
    if runs.empty:
        print("WARNING: No disagreement analysis runs found")
        return True

    df = pd.DataFrame(runs)
    print(f"Disagreement runs: {len(df)}")
    return True


def check_config_frozen():
    """T06.5: config/models.yaml frozen."""
    import yaml

    try:
        with open("config/models.yaml") as f:
            config = yaml.safe_load(f)
        required = [
            "asr_model",
            "asr_model_revision",
            "embedding_model",
            "embedding_dim",
            "embedding_revision",
        ]
        for key in required:
            if key not in config:
                print(f"FAIL: Missing {key} in config/models.yaml")
                return False
        print("PASS: config/models.yaml frozen with all required keys")
        print(f"  asr_model: {config['asr_model']}")
        print(f"  embedding_model: {config['embedding_model']} ({config['embedding_dim']}d)")
        return True
    except FileNotFoundError:
        print("FAIL: config/models.yaml not found")
        return False


def main():
    print("=" * 50)
    print("S06 GATE CHECK")
    print("=" * 50)

    all_pass = True
    all_pass &= check_asr_gate()
    all_pass &= check_embedding_gate()
    all_pass &= check_worst_condition()
    all_pass &= check_disagreement()
    all_pass &= check_config_frozen()

    print("=" * 50)
    if all_pass:
        print("ALL GATES PASSED — S06 COMPLETE")
        return 0
    else:
        print("GATE FAILURE — PROJECT HALTS")
        return 1


if __name__ == "__main__":
    sys.exit(main())
