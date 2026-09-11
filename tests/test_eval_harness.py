import pytest
from src.eval.harness import SEGEVAL_FIXTURES, WER_FIXTURE, DatasetType, run_eval


class TestWER:
    def test_known_fixture(self):
        result = run_eval(DatasetType.WER, WER_FIXTURE["reference"], WER_FIXTURE["predictions"])
        assert result.wer is not None
        assert abs(result.wer - WER_FIXTURE["expected_wer"]) < 0.001

    def test_perfect_match(self):
        ref = ["hello world", "test case"]
        pred = ["hello world", "test case"]
        result = run_eval(DatasetType.WER, ref, pred)
        assert result.wer == 0.0

    def test_complete_mismatch(self):
        ref = ["hello world"]
        pred = ["completely different words"]
        result = run_eval(DatasetType.WER, ref, pred)
        assert result.wer > 0.5


class TestSegmentation:
    def test_identical_segmentations(self):
        fixture = SEGEVAL_FIXTURES["identical"]
        result = run_eval(DatasetType.SEGMENTATION, fixture["reference"], fixture["predictions"])
        assert result.pk == 0.0
        assert result.window_diff == 0.0

    def test_inverted_segmentation(self):
        fixture = SEGEVAL_FIXTURES["inverted"]
        result = run_eval(DatasetType.SEGMENTATION, fixture["reference"], fixture["predictions"])
        assert result.pk > 0.0

    def test_single_segment(self):
        ref = [[10]]
        pred = [[10]]
        result = run_eval(DatasetType.SEGMENTATION, ref, pred)
        assert result.pk == 0.0


class TestClustering:
    def test_perfect_clustering(self):
        ref = [0, 0, 1, 1, 2, 2]
        pred = [0, 0, 1, 1, 2, 2]
        result = run_eval(DatasetType.CLUSTERING, ref, pred)
        assert result.purity == 1.0
        assert result.v_measure == 1.0

    def test_random_clustering(self):
        ref = [0, 0, 1, 1, 2, 2]
        pred = [1, 1, 0, 0, 2, 2]
        result = run_eval(DatasetType.CLUSTERING, ref, pred)
        assert result.purity == 1.0
        assert result.v_measure == 1.0


class TestRelevance:
    def test_perfect_agreement(self):
        ref = [1, 0, 1, 1, 0, 1, 0, 0]
        pred = [1, 0, 1, 1, 0, 1, 0, 0]
        result = run_eval(DatasetType.RELEVANCE, ref, pred)
        assert result.kappa == 1.0

    def test_chance_agreement(self):
        ref = [1, 0, 1, 0, 1, 0, 1, 0]
        pred = [0, 1, 0, 1, 0, 1, 0, 1]
        result = run_eval(DatasetType.RELEVANCE, ref, pred)
        assert result.kappa <= 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
