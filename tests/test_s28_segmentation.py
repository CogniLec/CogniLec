"""Tests for S28 - TextTiling-style boundary detection (T28.1-T28.5)."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

import numpy as np
from hypothesis import given
from hypothesis import strategies as st
from src.ml.clustering.segmentation import segment_session


@dataclass
class _Utt:
    id: uuid.UUID


def _utterances(n: int) -> list[_Utt]:
    return [_Utt(id=uuid.uuid4()) for _ in range(n)]


class TestT281T282StructuralValidity:
    @given(
        n=st.integers(min_value=2, max_value=80), seed=st.integers(min_value=0, max_value=10_000)
    )
    def test_contiguous_ordered_nonoverlapping(self, n: int, seed: int) -> None:
        """T28.1/T28.2: segments are contiguous, ordered, non-overlapping and
        every utterance index appears exactly once."""
        rng = np.random.default_rng(seed)
        embeddings = rng.random((n, 16)).tolist()
        utterances = _utterances(n)

        result = segment_session(utterances, embeddings)

        covered: list[int] = []
        prev_end = -1
        for seg in result.segments:
            assert seg.start_idx == prev_end + 1
            assert seg.start_idx <= seg.end_idx
            covered.extend(range(seg.start_idx, seg.end_idx + 1))
            prev_end = seg.end_idx
        assert prev_end == n - 1
        assert covered == list(range(n))


class TestT284SingleTopicNoSpuriousSplits:
    def test_identical_embeddings_single_segment(self) -> None:
        """T28.4: a single-topic transcript (identical embeddings) yields one segment."""
        n = 30
        utterances = _utterances(n)
        embeddings = [[1.0, 0.0, 0.0] for _ in range(n)]

        result = segment_session(utterances, embeddings)

        assert result.num_segments == 1
        assert result.segments[0].start_idx == 0
        assert result.segments[0].end_idx == n - 1


class TestT283SyntheticBoundaryRecovery:
    def test_three_known_boundaries_recovered(self) -> None:
        """T28.3: 3 sharply distinct topic blocks recover boundaries within +/-2."""
        block_a = [[1.0, 0.0, 0.0] for _ in range(10)]
        block_b = [[0.0, 1.0, 0.0] for _ in range(10)]
        block_c = [[0.0, 0.0, 1.0] for _ in range(10)]
        embeddings = block_a + block_b + block_c
        utterances = _utterances(30)

        result = segment_session(utterances, embeddings, threshold_percentile=50.0)

        boundary_indices = sorted(seg.end_idx for seg in result.segments[:-1])
        expected = [9, 19]
        assert len(boundary_indices) >= 2
        for exp in expected:
            assert any(abs(b - exp) <= 2 for b in boundary_indices)


class TestT285Performance:
    def test_1000_utterances_under_10s(self) -> None:
        n = 1000
        rng = np.random.default_rng(0)
        embeddings = rng.random((n, 1024)).tolist()
        utterances = _utterances(n)

        start = time.monotonic()
        result = segment_session(utterances, embeddings)
        elapsed = time.monotonic() - start

        assert elapsed < 10.0
        assert result.num_segments >= 1


class TestEdgeCases:
    def test_empty_utterances(self) -> None:
        result = segment_session([], [])
        assert result.segments == []
        assert result.num_segments == 0

    def test_single_utterance(self) -> None:
        result = segment_session(_utterances(1), [[1.0, 2.0]])
        assert result.num_segments == 1
        assert result.segments[0].start_idx == 0
        assert result.segments[0].end_idx == 0

    def test_dimension_mismatch_raises(self) -> None:
        import pytest

        with pytest.raises(ValueError):
            segment_session(_utterances(3), [[1.0], [1.0]])
