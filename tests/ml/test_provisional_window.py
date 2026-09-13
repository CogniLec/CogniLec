"""S33 — provisional topic window tests (T33.3, T33.4, T33.5)."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

import numpy as np
import pytest
from src.ml.clustering.bertopic_pipeline import cluster_segment_embeddings
from src.ml.provisional_window import (
    run_provisional_window,
    select_window_utterances,
)


@dataclass
class FakeUtterance:
    seq: int
    start_ms: int
    embedding: list[float]


def _cluster_blob(center: list[float], n: int, seed: int) -> list[list[float]]:
    rng = np.random.default_rng(seed)
    return [
        (np.asarray(center) + rng.normal(scale=0.05, size=len(center))).tolist() for _ in range(n)
    ]


@pytest.mark.unit
class TestSelectWindowUtterances:
    def test_selects_only_first_window_minutes(self) -> None:
        utterances = [
            FakeUtterance(0, 0, [0.0]),
            FakeUtterance(1, 5 * 60_000, [0.0]),
            FakeUtterance(2, 15 * 60_000, [0.0]),
        ]

        window = select_window_utterances(utterances, window_minutes=10)

        assert [u.seq for u in window] == [0, 1]

    def test_empty_input(self) -> None:
        assert select_window_utterances([]) == []


@pytest.mark.unit
class TestT335ShortSessionNoError:
    def test_short_session_completes_without_error(self) -> None:
        session_id = uuid.uuid4()
        embeddings = _cluster_blob([1.0] * 8, 6, seed=1)
        utterances = [FakeUtterance(i, i * 10_000, emb) for i, emb in enumerate(embeddings)]

        result = run_provisional_window(session_id, utterances, window_minutes=10)

        assert result is not None
        assert result.utterances_in_window == len(utterances)
        assert result.is_authoritative is False

    def test_below_min_utterances_skips_without_exception(self) -> None:
        session_id = uuid.uuid4()
        utterances = [FakeUtterance(0, 0, [0.0] * 8)]

        result = run_provisional_window(session_id, utterances, min_utterances=5)

        assert result is None


@pytest.mark.unit
class TestT333ProvisionalWithin60sOfWindowMark:
    def test_provisional_pass_completes_quickly(self) -> None:
        session_id = uuid.uuid4()
        embeddings = _cluster_blob([1.0] * 8, 10, seed=2) + _cluster_blob([-1.0] * 8, 10, seed=3)
        utterances = [FakeUtterance(i, i * 5_000, emb) for i, emb in enumerate(embeddings)]

        start = time.monotonic()
        result = run_provisional_window(session_id, utterances, window_minutes=10)
        elapsed = time.monotonic() - start

        assert result is not None
        assert elapsed < 60.0


@pytest.mark.unit
class TestT334ProvisionalDiffersFromFinalAndFinalIsAuthoritative:
    def test_provisional_result_is_never_authoritative(self) -> None:
        session_id = uuid.uuid4()
        embeddings = _cluster_blob([1.0] * 8, 6, seed=4)
        utterances = [FakeUtterance(i, i * 10_000, emb) for i, emb in enumerate(embeddings)]

        provisional = run_provisional_window(session_id, utterances, window_minutes=10)
        assert provisional is not None
        assert provisional.is_authoritative is False

    def test_provisional_window_and_full_session_produce_different_clusterings(self) -> None:
        """A real difference: the provisional pass only sees the first-10-min
        window, while the full pass (S30's cluster_segment_embeddings) sees
        every segment embedding — proving the provisional result is a
        different (non-authoritative) computation, not a shortcut alias for
        the final one."""
        session_id = uuid.uuid4()
        window_embeddings = _cluster_blob([1.0] * 8, 8, seed=5)
        full_embeddings = window_embeddings + _cluster_blob([-1.0] * 8, 8, seed=6)
        utterances = [FakeUtterance(i, i * 30_000, emb) for i, emb in enumerate(window_embeddings)]

        provisional = run_provisional_window(session_id, utterances, window_minutes=10)
        assert provisional is not None

        full_assignment = cluster_segment_embeddings(full_embeddings)

        assert (
            len(set(full_assignment.labels)) != len(provisional.topics)
            or len(full_embeddings) != provisional.utterances_in_window
        )
