import numpy as np
from src.services.quality.reward import aggregate, coverage, diversity


def test_coverage_full_and_none():
    u = np.eye(3)
    assert coverage(u, np.eye(3)) == 1.0
    assert coverage(u, np.array([[1.0, 1.0, 1.0]]) * 0 + np.array([[0, 0, 0]])) == 0.0
    assert coverage(u, np.empty((0, 3))) == 0.0


def test_diversity_duplicates_vs_orthogonal():
    assert diversity(np.array([[1.0, 0], [1.0, 0]])) == 0.0
    assert diversity(np.eye(3)) == 1.0
    assert diversity(np.eye(3)[:1]) == 0.0


def test_aggregate_zero_term_collapses_and_unjudged_flag():
    r = aggregate({"coverage": 0.0, "diversity": 1.0})
    assert r.reward == 0.0 and not r.judged
    r = aggregate(
        {
            "coverage": 0.8,
            "note_coverage": 0.8,
            "diversity": 0.8,
            "validity": 0.8,
            "provenance": 0.8,
        }
    )
    assert abs(r.reward - 0.8) < 1e-9 and r.judged
    assert aggregate({"validity": None}).reward == 0.0
