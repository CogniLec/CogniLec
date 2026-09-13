"""S06 Clustering evaluation tests — offline, no GPU required."""

from __future__ import annotations

import numpy as np
from src.ml.clustering.evaluate import (
    compute_ari,
    compute_nmi,
    compute_purity,
    compute_silhouette,
    compute_v_measure,
)


class TestComputePurity:
    def test_perfect_clustering(self):
        true = [0, 0, 1, 1, 2, 2]
        pred = [0, 0, 1, 1, 2, 2]
        assert compute_purity(true, pred) == 1.0

    def test_imperfect_clustering(self):
        true = [0, 0, 1, 1]
        pred = [0, 0, 0, 1]  # one 0 misclustered as 1, one 1 as 0 — but 0 cluster is pure
        purity = compute_purity(true, pred)
        assert 0.5 <= purity <= 1.0

    def test_all_noise(self):
        true = [0, 1, 2]
        pred = [-1, -1, -1]
        assert compute_purity(true, pred) == 0.0

    def test_single_cluster(self):
        true = [0, 0, 1, 1]
        pred = [0, 0, 0, 0]
        # Hungarian picks best match — 2/4 = 0.5
        assert compute_purity(true, pred) == 0.5


class TestComputeVMeasure:
    def test_perfect(self):
        true = [0, 0, 1, 1]
        pred = [0, 0, 1, 1]
        assert compute_v_measure(true, pred) == 1.0

    def test_worst(self):
        true = [0, 0, 1, 1]
        pred = [0, 1, 0, 1]
        v = compute_v_measure(true, pred)
        assert v < 0.5


class TestComputeSilhouette:
    def test_well_separated(self):
        embeddings = np.array(
            [
                [0, 0],
                [0.1, 0],
                [0, 0.1],  # cluster 0
                [10, 10],
                [10.1, 10],
                [10, 10.1],  # cluster 1
            ]
        )
        labels = [0, 0, 0, 1, 1, 1]
        sil = compute_silhouette(embeddings, labels, metric="euclidean")
        assert sil > 0.8

    def test_all_noise(self):
        embeddings = np.array([[1, 2], [3, 4]])
        labels = [-1, -1]
        assert compute_silhouette(embeddings, labels) == 0.0

    def test_single_cluster(self):
        embeddings = np.array([[1, 2], [3, 4]])
        labels = [0, 0]
        assert compute_silhouette(embeddings, labels) == 0.0


class TestComputeNMI:
    def test_perfect(self):
        true = [0, 0, 1, 1]
        pred = [0, 0, 1, 1]
        assert compute_nmi(true, pred) == 1.0

    def test_random(self):
        true = [0, 0, 1, 1]
        pred = [0, 1, 0, 1]
        assert compute_nmi(true, pred) < 0.5


class TestComputeARI:
    def test_perfect(self):
        true = [0, 0, 1, 1]
        pred = [0, 0, 1, 1]
        assert compute_ari(true, pred) == 1.0

    def test_worst(self):
        true = [0, 0, 1, 1]
        pred = [0, 1, 0, 1]
        ari = compute_ari(true, pred)
        assert ari < 0.5
