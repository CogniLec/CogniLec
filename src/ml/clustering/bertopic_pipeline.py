"""S30 — mean-pooling + BERTopic (UMAP+HDBSCAN) clustering over segment embeddings.

Pure functions, no DB/Prefect dependency, so they're directly unit-testable
(the S06 bake-off already validated these hyperparameters).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

UMAP_CONFIG: dict[str, int | str] = {
    "n_neighbors": 15,
    "n_components": 5,
    "metric": "cosine",
    "random_state": 42,
}

HDBSCAN_CONFIG: dict[str, int | str] = {
    "min_cluster_size": 5,
    "min_samples": 3,
    "metric": "euclidean",
    "cluster_selection_method": "eom",
}


def mean_pool_segment(embeddings: list[list[float]]) -> list[float]:
    """Mean-pool utterance embeddings within a segment (S30 §6.2)."""
    pooled = np.mean(np.asarray(embeddings, dtype=float), axis=0)
    return [float(x) for x in pooled.tolist()]


@dataclass
class ClusterAssignment:
    labels: list[int]  # -1 = HDBSCAN outlier/noise
    outlier_scores: list[float]  # 0 (core) .. 1 (pure noise)
    centroids: dict[int, list[float]]  # cluster label -> mean embedding


def _single_topic_fallback(
    arr: np.ndarray[tuple[int, ...], np.dtype[np.float64]],
) -> ClusterAssignment:
    """Collapse every point into one topic (S30 §6.5's n==1 pattern, reused
    for the "HDBSCAN found 0 real clusters" case -- see module docstring
    on `cluster_segment_embeddings` for why this exists)."""
    n = len(arr)
    return ClusterAssignment(
        labels=[0] * n,
        outlier_scores=[0.0] * n,
        centroids={0: np.mean(arr, axis=0).tolist()},
    )


def cluster_segment_embeddings(
    embeddings: list[list[float]],
    min_cluster_size: int | None = None,
) -> ClusterAssignment:
    """Cluster segment embeddings with UMAP+HDBSCAN (S30 §6.1).

    Falls back to a single cluster when there are too few segments for
    UMAP/HDBSCAN to run meaningfully (S30 §6.5: 0/1 segment cases), AND
    when HDBSCAN runs but finds zero real clusters for a small-but-not-
    trivial session (confirmed live: a real 7-segment recording produced
    0 topics because the fixed min_cluster_size=5 default was only ever
    validated against 30+-point test data -- see docs/gaps.md #33e and
    spec §6.1/§6.5, updated alongside this fix).

    Two changes from the original fixed-min_cluster_size design:
    1. When the caller doesn't override min_cluster_size, it now scales
       with n (`max(2, min(default, ceil(n/3)))`) instead of staying
       fixed at the module default -- a 7-point session now targets
       clusters of ~3, not an arbitrary 5 that guarantees failure on
       short real recordings.
    2. If HDBSCAN still finds 0 real clusters (every point labeled -1)
       even after that, all points collapse into a single topic rather
       than leaving `topics_created=0` as a silently "valid" outcome --
       "the content had no distinct sub-topics" is a legitimate finding,
       "there is no topic at all" should never happen for n>=2 real
       segments, since it's what causes flashcard generation to have
       nothing to retrieve against downstream.
    """
    n = len(embeddings)
    if n == 0:
        return ClusterAssignment(labels=[], outlier_scores=[], centroids={})
    if n == 1:
        return ClusterAssignment(labels=[0], outlier_scores=[0.0], centroids={0: embeddings[0]})

    arr = np.asarray(embeddings, dtype=float)
    default_mcs = int(min_cluster_size or HDBSCAN_CONFIG["min_cluster_size"])
    if min_cluster_size is None:
        # Scale to n instead of staying fixed -- see docstring above.
        default_mcs = min(default_mcs, math.ceil(n / 3))
    mcs = max(2, min(default_mcs, n))

    reduced = arr
    n_components = int(UMAP_CONFIG["n_components"])
    if n > n_components + 1:
        import umap

        reducer = umap.UMAP(
            n_neighbors=min(int(UMAP_CONFIG["n_neighbors"]), n - 1),
            n_components=min(n_components, n - 2),
            metric=UMAP_CONFIG["metric"],
            random_state=UMAP_CONFIG["random_state"],
        )
        reduced = reducer.fit_transform(arr)

    import hdbscan

    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=mcs,
        min_samples=min(HDBSCAN_CONFIG["min_samples"], mcs),
        metric=HDBSCAN_CONFIG["metric"],
        cluster_selection_method=HDBSCAN_CONFIG["cluster_selection_method"],
    )
    labels = clusterer.fit_predict(reduced)
    probabilities = getattr(clusterer, "probabilities_", np.ones(n))
    outlier_scores = [
        0.0 if lbl != -1 else 1.0 - float(p) for lbl, p in zip(labels, probabilities, strict=True)
    ]

    centroids: dict[int, list[float]] = {}
    for lbl in set(labels):
        if lbl == -1:
            continue
        mask = labels == lbl
        centroids[int(lbl)] = np.mean(arr[mask], axis=0).tolist()

    if not centroids:
        return _single_topic_fallback(arr)

    return ClusterAssignment(
        labels=[int(x) for x in labels], outlier_scores=outlier_scores, centroids=centroids
    )
