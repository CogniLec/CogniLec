#!/usr/bin/env python3
"""S06 Embedding Bake-Off — Qwen3-Embedding-0.6B + BERTopic clustering.

Evaluates embedding quality via purity and V-measure on S05 labeled data.
"""

import json
import logging
import os
import sys
import time
from pathlib import Path

import mlflow
import numpy as np
import pandas as pd
import torch

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

MLFLOW_URI = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")
EXPERIMENT_NAME = "S06_Embedding_Bakeoff"

EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-0.6B"
EMBEDDING_DIM = 1024
BATCH_SIZE = 32

# BERTopic hyperparameters
UMAP_N_NEIGHBORS = 15
UMAP_N_COMPONENTS = 5
UMAP_METRIC = "cosine"
HDBSCAN_MIN_CLUSTER_SIZE = 5
HDBSCAN_MIN_SAMPLES = 3
HDBSCAN_METRIC = "euclidean"
HDBSCAN_CLUSTER_SELECTION = "eom"

SEED = 42


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def load_s05_labeled_data() -> tuple[list[str], list[int], list[str]]:
    """Load S05 hand-transcribed texts with topic labels.

    Returns:
        texts: list of transcript strings
        labels: integer topic labels
        label_names: human-readable topic names
    """
    gt_dir = Path("data/ground_truth")
    texts: list[str] = []
    labels: list[int] = []
    label_names: list[str] = []
    label_map: dict[str, int] = {}

    for json_file in sorted(gt_dir.glob("*.json")):
        try:
            with open(json_file) as f:
                data = json.load(f)
            transcript = data.get("transcript", data.get("text", ""))
            topic = data.get("topic", data.get("label", "unknown"))
            if not transcript.strip():
                continue
            if topic not in label_map:
                label_map[topic] = len(label_map)
            texts.append(transcript)
            labels.append(label_map[topic])
            label_names.append(topic)
        except Exception as e:
            log.warning("Skipping %s: %s", json_file.name, e)

    if not texts:
        # Fallback: use txt files
        for txt_file in sorted(gt_dir.glob("*.txt")):
            transcript = txt_file.read_text().strip()
            if transcript:
                topic = txt_file.stem.split("_")[0] if "_" in txt_file.stem else "unknown"
                if topic not in label_map:
                    label_map[topic] = len(label_map)
                texts.append(transcript)
                labels.append(label_map[topic])
                label_names.append(topic)

    log.info("Loaded %d labeled texts across %d topics", len(texts), len(label_map))
    return texts, labels, label_names


# ---------------------------------------------------------------------------
# Embedding + clustering
# ---------------------------------------------------------------------------
def run_embedding_bakeoff():
    mlflow.set_tracking_uri(MLFLOW_URI)
    mlflow.set_experiment(EXPERIMENT_NAME)

    texts, labels, label_names = load_s05_labeled_data()
    if len(texts) < 10:
        log.error("Insufficient labeled data (%d texts). Need >= 10.", len(texts))
        sys.exit(1)

    log.info("Embedding %d texts with %s", len(texts), EMBEDDING_MODEL)

    # Load embedding model
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(EMBEDDING_MODEL, device="cuda")
    log.info("Model loaded — generating embeddings...")

    t0 = time.time()
    embeddings = model.encode(
        texts,
        batch_size=BATCH_SIZE,
        show_progress_bar=True,
        normalize_embeddings=True,
    )
    encode_time = time.time() - t0
    log.info("Embeddings shape: %s — took %.1fs", embeddings.shape, encode_time)

    # BERTopic clustering
    from bertopic import BERTopic
    from hdbscan import HDBSCAN
    from sklearn.metrics import silhouette_score
    from umap import UMAP

    umap_model = UMAP(
        n_neighbors=UMAP_N_NEIGHBORS,
        n_components=UMAP_N_COMPONENTS,
        metric=UMAP_METRIC,
        random_state=SEED,
    )

    hdbscan_model = HDBSCAN(
        min_cluster_size=HDBSCAN_MIN_CLUSTER_SIZE,
        min_samples=HDBSCAN_MIN_SAMPLES,
        metric=HDBSCAN_METRIC,
        cluster_selection_method=HDBSCAN_CLUSTER_SELECTION,
    )

    topic_model = BERTopic(
        embedding_model=model,
        umap_model=umap_model,
        hdbscan_model=hdbscan_model,
        calculate_probabilities=True,
        verbose=True,
    )

    log.info("Fitting BERTopic...")
    topics, probs = topic_model.fit_transform(texts, embeddings)

    # Compute clustering metrics
    from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score, v_measure_score

    # Purity: each predicted cluster should contain mostly one true label
    topics_arr = np.array(topics)
    labels_arr = np.array(labels)

    # Filter out noise points (topic == -1) for purity calculation
    non_noise = topics_arr != -1
    if non_noise.sum() > 0:
        filtered_topics = topics_arr[non_noise]
        filtered_labels = labels_arr[non_noise]

        # Purity calculation
        from scipy.optimize import linear_sum_assignment
        from scipy.special import comb

        n_clusters = len(set(filtered_topics))
        n_true = len(set(filtered_labels))
        confusion = np.zeros((n_clusters, n_true), dtype=int)
        for i, (t, l) in enumerate(zip(filtered_topics, filtered_labels)):
            cluster_idx = list(sorted(set(filtered_topics))).index(t)
            confusion[cluster_idx, l] += 1

        row_ind, col_ind = linear_sum_assignment(-confusion)
        purity = confusion[row_ind, col_ind].sum() / len(filtered_topics)

        # V-measure
        v_measure = v_measure_score(filtered_labels, filtered_topics)

        # Silhouette (on non-noise points)
        if len(set(filtered_topics)) > 1:
            silhouette = silhouette_score(embeddings[non_noise], filtered_topics, metric="cosine")
        else:
            silhouette = 0.0
    else:
        purity = 0.0
        v_measure = 0.0
        silhouette = 0.0

    # NMI and ARI
    nmi = normalized_mutual_info_score(labels_arr, topics_arr)
    ari = adjusted_rand_score(labels_arr, topics_arr)

    log.info("Clustering metrics:")
    log.info("  Purity:      %.3f", purity)
    log.info("  V-measure:   %.3f", v_measure)
    log.info("  Silhouette:  %.3f", silhouette)
    log.info("  NMI:         %.3f", nmi)
    log.info("  ARI:         %.3f", ari)

    # Log to MLflow
    with mlflow.start_run(run_name=f"qwen3-0.6b_{EMBEDDING_DIM}d"):
        mlflow.log_params(
            {
                "model": EMBEDDING_MODEL,
                "dim": EMBEDDING_DIM,
                "umap_n_neighbors": UMAP_N_NEIGHBORS,
                "umap_n_components": UMAP_N_COMPONENTS,
                "hdbscan_min_cluster_size": HDBSCAN_MIN_CLUSTER_SIZE,
                "hdbscan_min_samples": HDBSCAN_MIN_SAMPLES,
                "num_texts": len(texts),
                "num_topics": len(set(topics)),
                "num_noise_points": int((topics_arr == -1).sum()),
                "encode_time_sec": encode_time,
                "batch_size": BATCH_SIZE,
                "seed": SEED,
            }
        )

        mlflow.log_metrics(
            {
                "purity": purity,
                "v_measure": v_measure,
                "silhouette": silhouette,
                "nmi": nmi,
                "ari": ari,
            }
        )

        # Log topic info
        topic_info = topic_model.get_topic_info()
        csv_path = Path("tmp_topic_info.csv")
        topic_info.to_csv(csv_path, index=False)
        mlflow.log_artifact(str(csv_path), "topic_info")
        csv_path.unlink(missing_ok=True)

        # Log cluster labels
        labels_path = Path("tmp_cluster_labels.json")
        labels_path.write_text(
            json.dumps(
                {
                    "topics": topics,
                    "label_names": label_names,
                    "true_labels": labels,
                }
            )
        )
        mlflow.log_artifact(str(labels_path), "cluster_labels")
        labels_path.unlink(missing_ok=True)

    # Save embedding results CSV
    emb_df = pd.DataFrame(
        [
            {
                "model": "qwen3-0.6b",
                "dim": EMBEDDING_DIM,
                "purity": purity,
                "v_measure": v_measure,
                "silhouette": silhouette,
                "nmi": nmi,
                "ari": ari,
                "umap_n_neighbors": UMAP_N_NEIGHBORS,
                "hdbscan_min_cluster_size": HDBSCAN_MIN_CLUSTER_SIZE,
            }
        ]
    )
    csv_path = Path("docs/bakeoff-embedding-results.csv")
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    emb_df.to_csv(csv_path, index=False)
    log.info("Embedding results saved to %s", csv_path)

    return purity


if __name__ == "__main__":
    try:
        run_embedding_bakeoff()
        log.info("Embedding bake-off complete")
    except Exception as e:
        log.error("Embedding bake-off failed: %s", e, exc_info=True)
        sys.exit(1)
