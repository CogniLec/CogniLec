#!/usr/bin/env python3
"""S06 Disagreement Analysis — Pairwise ASR model disagreement and error correlation."""

import logging
import os
import sys
from pathlib import Path

import mlflow
import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

MLFLOW_URI = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")
EXPERIMENT_NAME = "S06_Disagreement_Analysis"


def load_asr_results() -> pd.DataFrame:
    """Load ASR bake-off results from CSV or MLflow."""
    csv_path = Path("docs/bakeoff-asr-results.csv")
    if csv_path.exists():
        return pd.read_csv(csv_path)

    # Fallback: load from MLflow
    mlflow.set_tracking_uri(MLFLOW_URI)
    runs = mlflow.search_runs(experiment_names=["S06_ASR_Bakeoff"])
    if runs.empty:
        log.error("No ASR results found")
        sys.exit(1)
    return pd.DataFrame(runs)


def pairwise_disagreement(
    hyp_a: list[str], hyp_b: list[str], ref: list[str]
) -> tuple[float, float]:
    """Compute disagreement rate and WER correlation between two model hypotheses.

    Returns:
        disagreement_rate: fraction of files where models disagree on WER direction
        wer_correlation: Pearson correlation of per-file WERs
    """
    import jiwer

    def normalize(text: str) -> str:
        return jiwer.ToLowerCase()(
            jiwer.RemovePunctuation()(jiwer.RemoveMultipleSpaces()(text.strip()))
        )

    wer_a_list: list[float] = []
    wer_b_list: list[float] = []
    disagreements = 0

    for ha, hb, r in zip(hyp_a, hyp_b, ref):
        na, nb, nr = normalize(ha), normalize(hb), normalize(r)
        try:
            w_a = jiwer.wer(nr, na)
            w_b = jiwer.wer(nr, nb)
        except ValueError:
            continue
        wer_a_list.append(w_a)
        wer_b_list.append(w_b)
        # Disagreement: models differ on which is "closer" to reference
        if (w_a < w_b and ha != hb) or (w_a > w_b and ha != hb):
            disagreements += 1

    n = len(wer_a_list)
    if n == 0:
        return 0.0, 0.0

    disagreement_rate = disagreements / n
    correlation = np.corrcoef(wer_a_list, wer_b_list)[0, 1] if n > 1 else 0.0
    return disagreement_rate, float(correlation)


def load_model_hypotheses() -> dict[str, dict[str, str]]:
    """Load per-model, per-file hypotheses from MLflow artifacts.

    Returns:
        {model_name: {audio_file: hypothesis_text}}
    """
    # Simplified: load from CSV if available, otherwise return empty
    hypotheses: dict[str, dict[str, str]] = {}
    artifact_dir = Path("docs/bakeoff-hypotheses")
    if artifact_dir.exists():
        for model_dir in artifact_dir.iterdir():
            if model_dir.is_dir():
                model_name = model_dir.name
                hypotheses[model_name] = {}
                for hyp_file in model_dir.glob("*.txt"):
                    hypotheses[model_name][hyp_file.stem] = hyp_file.read_text()
    return hypotheses


def run_disagreement_analysis():
    mlflow.set_tracking_uri(MLFLOW_URI)
    mlflow.set_experiment(EXPERIMENT_NAME)

    # Load per-file WER results from MLflow
    asr_runs = mlflow.search_runs(experiment_names=["S06_ASR_Bakeoff"])
    if asr_runs.empty:
        log.error("No ASR bake-off runs found. Run s06_asr_bakeoff.py first.")
        sys.exit(1)

    df = pd.DataFrame(asr_runs)

    # Group by model to get per-file WERs
    models = df["params.model"].unique().tolist()
    log.info("Found %d models: %s", len(models), models)

    pairwise_results: list[dict] = []

    for i, model_a in enumerate(models):
        for model_b in models[i + 1 :]:
            # Get WERs for files present in both models
            df_a = df[df["params.model"] == model_a].set_index("params.audio_file")
            df_b = df[df["params.model"] == model_b].set_index("params.audio_file")

            common_files = list(set(df_a.index) & set(df_b.index))
            if not common_files:
                log.warning("No common audio files between %s and %s", model_a, model_b)
                continue

            wer_a = df_a.loc[common_files, "metrics.wer"].values
            wer_b = df_b.loc[common_files, "metrics.wer"].values

            # Compute disagreement metrics
            n = len(common_files)
            disagreement_count = 0
            for wa, wb in zip(wer_a, wer_b):
                if abs(wa - wb) > 0.05:  # 5% WER difference threshold
                    disagreement_count += 1

            disagreement_rate = disagreement_count / n if n > 0 else 0.0
            wer_correlation = float(np.corrcoef(wer_a, wer_b)[0, 1]) if n > 1 else 0.0

            pairwise_results.append(
                {
                    "model_a": model_a,
                    "model_b": model_b,
                    "disagreement_rate": disagreement_rate,
                    "wer_correlation": wer_correlation,
                    "num_common_files": n,
                }
            )

            log.info(
                "%s vs %s: disagreement=%.1f%%, corr=%.3f (n=%d)",
                model_a,
                model_b,
                disagreement_rate * 100,
                wer_correlation,
                n,
            )

    # Log to MLflow
    for result in pairwise_results:
        with mlflow.start_run(run_name=f"disagree_{result['model_a']}_vs_{result['model_b']}"):
            mlflow.log_params(
                {
                    "model_a": result["model_a"],
                    "model_b": result["model_b"],
                }
            )
            mlflow.log_metrics(
                {
                    "disagreement_rate": result["disagreement_rate"],
                    "wer_correlation": result["wer_correlation"],
                    "num_common_files": result["num_common_files"],
                }
            )

    # Save CSV
    if pairwise_results:
        disagree_df = pd.DataFrame(pairwise_results)
        csv_path = Path("docs/bakeoff-disagreement.csv")
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        disagree_df.to_csv(csv_path, index=False)
        log.info("Disagreement results saved to %s", csv_path)

    return pairwise_results


if __name__ == "__main__":
    try:
        run_disagreement_analysis()
        log.info("Disagreement analysis complete")
    except Exception as e:
        log.error("Disagreement analysis failed: %s", e, exc_info=True)
        sys.exit(1)
