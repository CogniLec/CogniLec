"""Tests for S67 - embedding contrastive fine-tune (T67.1-T67.7).

`faiss-gpu` and a GPU are both unavailable (gap #2), so hard-negative
mining runs the same nearest-neighbour search in plain numpy (real logic,
brute-force instead of an ANN index) - see `embedding_finetune.py`'s
module docstring. T67.1/T67.2/T67.3 (real contrastive training improving
real held-out metrics) need an actual trained model to compare against the
Qwen3 baseline and are honest skips; the staged rollout/rollback
(T67.5/T67.6) reuses S25's `backfill_version`, already tested for real in
`tests/test_s25_embedding.py`, so it isn't re-tested here.
"""

from __future__ import annotations

import uuid

import numpy as np
import pytest
from src.services.finetuning.embedding_finetune import (
    build_contrastive_triplets,
    clustering_purity,
    mine_hard_negatives,
)


def test_t67_4_hard_negatives_are_confirmed_different_topic_not_same_topic():
    a1, a2 = uuid.uuid4(), uuid.uuid4()  # topic A
    b1, b2 = uuid.uuid4(), uuid.uuid4()  # topic B
    embeddings = {
        a1: np.array([1.0, 0.0, 0.0]),
        a2: np.array([0.95, 0.05, 0.0]),  # close to a1, same topic
        b1: np.array([0.9, 0.1, 0.0]),  # close to a1, different topic - hard negative
        b2: np.array([0.0, 0.0, 1.0]),  # far from everything
    }
    topic_of = {a1: "A", a2: "A", b1: "B", b2: "B"}

    negatives = mine_hard_negatives(embeddings, topic_of, top_k=1)
    by_anchor = {n.anchor_id: n for n in negatives}

    assert by_anchor[a1].negative_id == b1
    assert topic_of[by_anchor[a1].negative_id] != topic_of[a1]
    for negative in negatives:
        assert negative.negative_id != negative.anchor_id
        assert topic_of[negative.negative_id] != topic_of[negative.anchor_id]


def test_hard_negative_mining_handles_single_item_gracefully():
    only_id = uuid.uuid4()
    assert mine_hard_negatives({only_id: np.array([1.0, 0.0])}, {only_id: "A"}) == []


def test_build_contrastive_triplets_pairs_same_topic_positive_with_hard_negative():
    a1, a2, a3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    b1 = uuid.uuid4()
    embeddings = {
        a1: np.array([1.0, 0.0]),
        a2: np.array([0.9, 0.1]),
        a3: np.array([0.85, 0.15]),
        b1: np.array([0.8, 0.2]),
    }
    topic_of = {a1: "A", a2: "A", a3: "A", b1: "B"}
    triplets = build_contrastive_triplets(embeddings, topic_of)
    assert len(triplets) == 3
    for triplet in triplets:
        assert topic_of[triplet.anchor_id] == topic_of[triplet.positive_id]
        assert topic_of[triplet.negative_id] != topic_of[triplet.anchor_id]


def test_clustering_purity_perfect_clustering_scores_one():
    a1, a2, b1, b2 = (uuid.uuid4() for _ in range(4))
    predicted = {a1: "cluster_1", a2: "cluster_1", b1: "cluster_2", b2: "cluster_2"}
    truth = {a1: "topicA", a2: "topicA", b1: "topicB", b2: "topicB"}
    assert clustering_purity(predicted, truth) == 1.0


def test_clustering_purity_mixed_clustering_scores_below_one():
    a1, a2, b1 = (uuid.uuid4() for _ in range(3))
    predicted = {a1: "cluster_1", a2: "cluster_1", b1: "cluster_1"}
    truth = {a1: "topicA", a2: "topicA", b1: "topicB"}
    assert clustering_purity(predicted, truth) == pytest.approx(2 / 3)


@pytest.mark.skip(
    reason=(
        "T67.1-T67.3 require an actual sentence-transformers v3 contrastive "
        "training run on a GPU-loaded Qwen3-Embedding base model to compare "
        "clustering purity, cross-session matching accuracy and retrieval "
        "precision@5 before/after - no GPU-loaded model exists in this "
        "sandbox (gap #2, docs/gaps.md). The mining and triplet-building "
        "logic that would feed such a run is real and tested above."
    )
)
def test_t67_1_t67_2_t67_3_contrastive_training_improves_real_metrics():
    pass
