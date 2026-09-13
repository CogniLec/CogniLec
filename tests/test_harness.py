"""Tests for the test harness and synthetic generator."""

from __future__ import annotations

from src.eval.synthetic import SyntheticTranscriptGenerator


class TestSyntheticGenerator:
    def test_generates_correct_topic_count(self):
        gen = SyntheticTranscriptGenerator()
        result = gen.generate(num_topics=3, utterances_per_topic=10)
        assert result.num_topics == 3
        assert len(result.topic_labels) == 3

    def test_generates_correct_utterance_count(self):
        gen = SyntheticTranscriptGenerator()
        result = gen.generate(num_topics=2, utterances_per_topic=15)
        # Should have at least 2*15 = 30 utterances (may have off-topic)
        assert result.total_utterances >= 30

    def test_topic_boundaries_are_monotonic(self):
        gen = SyntheticTranscriptGenerator()
        result = gen.generate(num_topics=4, utterances_per_topic=10)
        for i in range(1, len(result.topic_boundaries)):
            assert result.topic_boundaries[i] > result.topic_boundaries[i - 1]

    def test_expected_segments_match_topics(self):
        gen = SyntheticTranscriptGenerator()
        result = gen.generate(num_topics=2, utterances_per_topic=10)
        assert len(result.expected_segments) == 2

    def test_seed_reproducibility(self):
        gen = SyntheticTranscriptGenerator()
        r1 = gen.generate(num_topics=2, utterances_per_topic=10, seed=42)
        r2 = gen.generate(num_topics=2, utterances_per_topic=10, seed=42)
        assert len(r1.utterances) == len(r2.utterances)
        for u1, u2 in zip(r1.utterances, r2.utterances):
            assert u1.text == u2.text

    def test_off_topic_included_when_enabled(self):
        gen = SyntheticTranscriptGenerator()
        result = gen.generate(
            num_topics=2,
            utterances_per_topic=50,
            include_off_topic=True,
            off_topic_ratio=0.5,
            seed=42,
        )
        off_topic_count = sum(1 for u in result.utterances if u.is_off_topic)
        assert off_topic_count > 0

    def test_off_topic_excluded_when_disabled(self):
        gen = SyntheticTranscriptGenerator()
        result = gen.generate(num_topics=2, utterances_per_topic=20, include_off_topic=False)
        off_topic_count = sum(1 for u in result.utterances if u.is_off_topic)
        assert off_topic_count == 0
