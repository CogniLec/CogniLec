"""Tests for S31 - topic labelling & keyword extraction (T31.3, T31.4, T31.5)."""

from __future__ import annotations

import uuid

from src.ml.clustering.keywords import extract_keywords
from src.ml.clustering.labelling import generate_topic_label


class TestT314SingleMemberCluster:
    def test_single_utterance_keywords(self) -> None:
        """T31.4: single-member cluster - no error, keywords returned."""
        results = extract_keywords(["gradient descent optimizes the loss function"])
        assert len(results) > 0
        assert all(r.score >= 0 for r in results)

    def test_empty_cluster_returns_empty(self) -> None:
        assert extract_keywords([]) == []

    def test_multi_utterance_ranks_by_frequency(self) -> None:
        texts = ["neural network training", "neural network layers", "gradient descent step"]
        results = extract_keywords(texts, n_keywords=5)
        keywords = [r.keyword for r in results]
        assert "neural network" in keywords


class TestT315LlmFailureFallback:
    async def test_connection_error_falls_back_to_placeholder(self) -> None:
        """T31.5: LLM raises ConnectionError -> placeholder label, pipeline continues."""

        class FailingClient:
            async def complete(self, prompt: str) -> str:
                raise ConnectionError("unreachable")

        topic_id = uuid.uuid4()
        label = await generate_topic_label(topic_id, ["utterance 1"], ["keyword1"], FailingClient())
        assert label == f"Topic {str(topic_id)[:8]}"

    async def test_successful_label_returned(self) -> None:
        class WorkingClient:
            async def complete(self, prompt: str) -> str:
                return "Introduction to Gradient Descent"

        topic_id = uuid.uuid4()
        label = await generate_topic_label(topic_id, ["u1"], ["gradient"], WorkingClient())
        assert label == "Introduction to Gradient Descent"

    async def test_empty_response_retries_then_placeholder(self) -> None:
        class EmptyClient:
            async def complete(self, prompt: str) -> str:
                return ""

        topic_id = uuid.uuid4()
        label = await generate_topic_label(topic_id, ["u1"], ["kw"], EmptyClient())
        assert label == f"Topic {str(topic_id)[:8]}"
