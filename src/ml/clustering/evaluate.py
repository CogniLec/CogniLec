"""Clustering evaluation metrics — purity, V-measure, silhouette."""

from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.metrics import (
    adjusted_rand_score,
    normalized_mutual_info_score,
    silhouette_score,
    v_measure_score,
)


def compute_purity(true_labels: list[int], predicted_labels: list[int]) -> float:
    """Compute clustering purity via the Hungarian algorithm.

    Purity = sum of max(confusion matrix column per cluster) / N.
    Noise points (predicted_label == -1) are excluded.

    Args:
        true_labels: ground-truth integer labels
        predicted_labels: cluster assignments (-1 for noise)

    Returns:
        Purity in [0, 1]
    """
    true_arr = np.array(true_labels)
    pred_arr = np.array(predicted_labels)

    non_noise = pred_arr != -1
    if non_noise.sum() == 0:
        return 0.0

    filtered_true = true_arr[non_noise]
    filtered_pred = pred_arr[non_noise]

    from scipy.optimize import linear_sum_assignment

    n_clusters = len(set(filtered_pred))
    n_true = len(set(filtered_true))
    confusion = np.zeros((n_clusters, n_true), dtype=int)

    unique_clusters = sorted(set(filtered_pred))
    for t, label in zip(filtered_pred, filtered_true):
        cluster_idx = unique_clusters.index(t)
        confusion[cluster_idx, label] += 1

    row_ind, col_ind = linear_sum_assignment(-confusion)
    purity = confusion[row_ind, col_ind].sum() / len(filtered_pred)
    return float(purity)


def compute_v_measure(true_labels: list[int], predicted_labels: list[int]) -> float:
    """Compute V-measure (harmonic mean of homogeneity and completeness).

    Args:
        true_labels: ground-truth integer labels
        predicted_labels: cluster assignments

    Returns:
        V-measure in [0, 1]
    """
    return float(v_measure_score(true_labels, predicted_labels))


def compute_silhouette(
    embeddings: np.ndarray[Any, np.dtype[np.floating[Any]]],
    predicted_labels: list[int],
    metric: str = "cosine",
) -> float:
    """Compute silhouette score on non-noise points.

    Args:
        embeddings: array of shape (N, dim)
        predicted_labels: cluster assignments (-1 for noise)
        metric: distance metric

    Returns:
        Silhouette score in [-1, 1]
    """
    pred_arr = np.array(predicted_labels)
    non_noise = pred_arr != -1

    if non_noise.sum() == 0 or len(set(pred_arr[non_noise])) <= 1:
        return 0.0

    return float(silhouette_score(embeddings[non_noise], pred_arr[non_noise], metric=metric))


def compute_nmi(true_labels: list[int], predicted_labels: list[int]) -> float:
    """Compute Normalized Mutual Information."""
    return float(normalized_mutual_info_score(true_labels, predicted_labels))


def compute_ari(true_labels: list[int], predicted_labels: list[int]) -> float:
    """Compute Adjusted Rand Index."""
    return float(adjusted_rand_score(true_labels, predicted_labels))
