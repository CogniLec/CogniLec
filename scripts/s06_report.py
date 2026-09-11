#!/usr/bin/env python3
"""S06 Report Generator — Produces CSV result tables and summary markdown."""

import logging
import os
import sys
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DOCS_DIR = Path("docs")


def generate_asr_report():
    """Aggregate ASR results from MLflow into a summary table."""
    import mlflow

    mlflow_uri = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")
    mlflow.set_tracking_uri(mlflow_uri)

    runs = mlflow.search_runs(experiment_names=["S06_ASR_Bakeoff"])
    if runs.empty:
        log.warning("No ASR bake-off runs found")
        return

    df = pd.DataFrame(runs)

    # Aggregate by model and condition
    agg = (
        df.groupby(["params.model", "params.condition"])
        .agg(
            wer_mean=("metrics.wer", "mean"),
            wer_median=("metrics.wer", "median"),
            wer_std=("metrics.wer", "std"),
            cer_mean=("metrics.cer", "mean"),
            rtf_mean=("metrics.rtf", "mean"),
            vram_peak_max=("metrics.vram_peak_mb", "max"),
            num_files=("metrics.wer", "count"),
        )
        .reset_index()
    )

    csv_path = DOCS_DIR / "bakeoff-asr-summary.csv"
    agg.to_csv(csv_path, index=False)
    log.info("ASR summary saved to %s", csv_path)

    # Per-model aggregate
    model_agg = (
        df.groupby("params.model")
        .agg(
            wer_mean=("metrics.wer", "mean"),
            wer_median=("metrics.wer", "median"),
            cer_mean=("metrics.cer", "mean"),
            rtf_mean=("metrics.rtf", "mean"),
            vram_peak_max=("metrics.vram_peak_mb", "max"),
            num_files=("metrics.wer", "count"),
        )
        .sort_values("wer_median")
        .reset_index()
    )

    model_csv = DOCS_DIR / "bakeoff-asr-model-summary.csv"
    model_agg.to_csv(model_csv, index=False)
    log.info("ASR model summary saved to %s", model_csv)

    return agg


def generate_embedding_report():
    """Aggregate embedding results from MLflow."""
    import mlflow

    mlflow_uri = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")
    mlflow.set_tracking_uri(mlflow_uri)

    runs = mlflow.search_runs(experiment_names=["S06_Embedding_Bakeoff"])
    if runs.empty:
        log.warning("No embedding bake-off runs found")
        return

    df = pd.DataFrame(runs)
    summary = df[
        [
            "params.model",
            "params.dim",
            "metrics.purity",
            "metrics.v_measure",
            "metrics.silhouette",
        ]
    ].copy()
    summary.columns = ["model", "dim", "purity", "v_measure", "silhouette"]

    csv_path = DOCS_DIR / "bakeoff-embedding-summary.csv"
    summary.to_csv(csv_path, index=False)
    log.info("Embedding summary saved to %s", csv_path)

    return summary


def generate_disagreement_report():
    """Load and display disagreement results."""
    csv_path = DOCS_DIR / "bakeoff-disagreement.csv"
    if not csv_path.exists():
        log.warning("No disagreement results found at %s", csv_path)
        return

    df = pd.read_csv(csv_path)
    log.info("Disagreement summary:")
    for _, row in df.iterrows():
        log.info(
            "  %s vs %s: disagreement=%.1f%%, corr=%.3f",
            row["model_a"],
            row["model_b"],
            row["disagreement_rate"] * 100,
            row["wer_correlation"],
        )
    return df


def generate_markdown_summary():
    """Generate a markdown summary of all bake-off results."""
    lines = ["# S06 Bake-Off Results Summary\n"]

    # ASR
    asr_csv = DOCS_DIR / "bakeoff-asr-model-summary.csv"
    if asr_csv.exists():
        df = pd.read_csv(asr_csv)
        lines.append("## ASR Model Comparison\n")
        lines.append("| Model | Median WER | Mean WER | CER | RTF | VRAM Peak |")
        lines.append("|-------|-----------|----------|-----|-----|-----------|")
        for _, row in df.iterrows():
            lines.append(
                f"| {row['params.model']} | {row['wer_median']:.3f} | "
                f"{row['wer_mean']:.3f} | {row['cer_mean']:.3f} | "
                f"{row['rtf_mean']:.3f} | {row['vram_peak_max']:.0f}MB |"
            )
        lines.append("")

    # Embedding
    emb_csv = DOCS_DIR / "bakeoff-embedding-summary.csv"
    if emb_csv.exists():
        df = pd.read_csv(emb_csv)
        lines.append("## Embedding Model Comparison\n")
        lines.append("| Model | Dim | Purity | V-measure | Silhouette |")
        lines.append("|-------|-----|--------|-----------|------------|")
        for _, row in df.iterrows():
            lines.append(
                f"| {row['model']} | {row['dim']} | {row['purity']:.3f} | "
                f"{row['v_measure']:.3f} | {row['silhouette']:.3f} |"
            )
        lines.append("")

    # Disagreement
    disagree_csv = DOCS_DIR / "bakeoff-disagreement.csv"
    if disagree_csv.exists():
        df = pd.read_csv(disagree_csv)
        lines.append("## Pairwise Disagreement\n")
        lines.append("| Model A | Model B | Disagreement Rate | WER Correlation |")
        lines.append("|---------|---------|-------------------|-----------------|")
        for _, row in df.iterrows():
            lines.append(
                f"| {row['model_a']} | {row['model_b']} | "
                f"{row['disagreement_rate']:.1%} | {row['wer_correlation']:.3f} |"
            )
        lines.append("")

    # Gate status
    lines.append("## Gate Status\n")
    lines.append("- **T06.1**: Best ASR WER < 20% on median condition")
    lines.append("- **T06.2**: Clustering purity > 0.60")
    lines.append("- **T06.3**: Worst condition WER recorded")
    lines.append("- **T06.4**: Pairwise ASR disagreement analysis")
    lines.append("- **T06.5**: config/models.yaml frozen")

    md_path = DOCS_DIR / "bakeoff-summary.md"
    md_path.write_text("\n".join(lines))
    log.info("Markdown summary saved to %s", md_path)


def main():
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    log.info("Generating S06 reports...")
    generate_asr_report()
    generate_embedding_report()
    generate_disagreement_report()
    generate_markdown_summary()
    log.info("All reports generated in %s/", DOCS_DIR)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log.error("Report generation failed: %s", e, exc_info=True)
        sys.exit(1)
