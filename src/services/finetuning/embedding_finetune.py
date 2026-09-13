"""S67 — embedding contrastive fine-tune: hard-negative mining and rollout.

The spec calls for hard negatives "mined with faiss-gpu" - no GPU and no
`faiss` package are available in this environment (gap #2), so
`mine_hard_negatives` below does the same nearest-neighbour search with
plain numpy cosine similarity over whatever embedding matrix it's handed.
The mining *logic* (find the closest different-topic neighbour, reject
same-topic and self matches) is real and exercised for real in tests; only
the ANN index implementation is a brute-force stand-in, same class of
substitution as S62's CLIP gap.

Actual contrastive training (sentence-transformers v3 `Trainer`) needs a
GPU-loaded base encoder to be worth running - see gap #2. The staged
rollout/rollback below reuses S25's `backfill_version` unchanged: rollout
is `backfill_version(from=old, to=new)` and rollback is the same call with
the arguments reversed, since it already re-embeds and writes
`embed_model_ver` per row, one subject at a time, resumably.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True)
class HardNegative:
    anchor_id: uuid.UUID
    negative_id: uuid.UUID
    similarity: float


def mine_hard_negatives(
    embeddings: dict[uuid.UUID, np.ndarray[Any, Any]],
    topic_of: dict[uuid.UUID, str],
    top_k: int = 1,
) -> list[HardNegative]:
    """For each anchor, find its nearest different-topic neighbour(s).

    A "hard negative" is embedding-close but topic-different - exactly the
    pairs that teach the model to separate topics it currently confuses.
    Same-topic neighbours and the anchor itself are never returned (T67.4).
    """
    ids = list(embeddings.keys())
    if len(ids) < 2:
        return []
    matrix = np.stack([embeddings[i] for i in ids])
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1e-9
    normalised = matrix / norms
    sims = normalised @ normalised.T

    results: list[HardNegative] = []
    for row_idx, anchor_id in enumerate(ids):
        anchor_topic = topic_of.get(anchor_id)
        scored = [
            (sims[row_idx, col_idx], ids[col_idx])
            for col_idx in range(len(ids))
            if col_idx != row_idx and topic_of.get(ids[col_idx]) != anchor_topic
        ]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        for similarity, negative_id in scored[:top_k]:
            results.append(
                HardNegative(
                    anchor_id=anchor_id, negative_id=negative_id, similarity=float(similarity)
                )
            )
    return results


@dataclass(frozen=True)
class ContrastivePair:
    anchor_id: uuid.UUID
    positive_id: uuid.UUID
    negative_id: uuid.UUID


def build_contrastive_triplets(
    embeddings: dict[uuid.UUID, np.ndarray[Any, Any]],
    topic_of: dict[uuid.UUID, str],
) -> list[ContrastivePair]:
    """Anchor/positive (same topic)/hard-negative (different topic) triplets.

    Feeds sentence-transformers v3's `TripletLoss` training format.
    """
    by_topic: dict[str, list[uuid.UUID]] = {}
    for item_id, topic in topic_of.items():
        by_topic.setdefault(topic, []).append(item_id)

    mined = mine_hard_negatives(embeddings, topic_of)
    hard_negatives = {hn.anchor_id: hn.negative_id for hn in mined}

    triplets: list[ContrastivePair] = []
    for topic, members in by_topic.items():
        if len(members) < 2:
            continue
        for i, anchor_id in enumerate(members):
            positive_id = members[(i + 1) % len(members)]
            negative_id = hard_negatives.get(anchor_id)
            if negative_id is not None:
                triplets.append(ContrastivePair(anchor_id, positive_id, negative_id))
    return triplets


def clustering_purity(
    predicted_topic_of: dict[uuid.UUID, str],
    true_topic_of: dict[uuid.UUID, str],
) -> float:
    """Fraction of items whose predicted-cluster majority label matches ground truth (S05).

    Standard clustering purity: group items by predicted cluster, take the
    majority true label in each group, sum the majority counts, divide by n.
    """
    by_predicted: dict[str, list[uuid.UUID]] = {}
    for item_id, cluster in predicted_topic_of.items():
        by_predicted.setdefault(cluster, []).append(item_id)

    total = len(predicted_topic_of)
    if total == 0:
        return 0.0

    correct = 0
    for members in by_predicted.values():
        labels = [true_topic_of.get(m) for m in members]
        counts: dict[str | None, int] = {}
        for label in labels:
            counts[label] = counts.get(label, 0) + 1
        correct += max(counts.values())
    return correct / total
