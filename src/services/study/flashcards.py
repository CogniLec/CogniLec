"""S58 — flashcard generation and performance-weighted selection.

Flashcards are generated per topic from the same retrieval path as A5
(S55's `RetrievalService`) but through a simple Q/A prompt rather than
A5's full question-type/difficulty schema - flashcards are a distinct
study artifact (front/back recall), not an assessment question.
"""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from dataclasses import dataclass

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from src.services.llm.router import LLMRouter
from src.services.retrieval.retrieval_service import retrieve


class GeneratedFlashcard(BaseModel):
    front: str = Field(min_length=1, max_length=500)
    back: str = Field(min_length=1, max_length=1000)


class FlashcardGenerationError(Exception):
    pass


def build_flashcard_prompt(
    topic_label: str, notes_context: str, count: int
) -> list[dict[str, str]]:
    system = (
        "Generate flashcards strictly from the given notes for one topic. "
        "Respond with a JSON array of exactly the requested count of "
        '{"front": short prompt/question string, "back": answer string} '
        "objects. Never invent content the notes don't support."
    )
    user = json.dumps({"topic": topic_label, "notes_context": notes_context, "count": count})
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def parse_flashcards(raw: str) -> list[GeneratedFlashcard]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        msg = f"non-JSON flashcard response: {exc}"
        raise FlashcardGenerationError(msg) from exc
    if not isinstance(payload, list):
        msg = "flashcard response must be a JSON array"
        raise FlashcardGenerationError(msg)
    try:
        return [GeneratedFlashcard.model_validate(item) for item in payload]
    except ValidationError as exc:
        msg = f"malformed flashcard: {exc}"
        raise FlashcardGenerationError(msg) from exc


class FlashcardGenerator:
    AGENT_ID = "A5_FLASHCARD_GEN"

    def __init__(self, router: LLMRouter, prompt_version: str = "v1.0.0") -> None:
        self._router = router
        self._prompt_version = prompt_version

    async def generate_for_topic(
        self, db: AsyncSession, subject_id: uuid.UUID, topic_label: str, count: int
    ) -> list[GeneratedFlashcard]:
        result = await retrieve(
            db,
            subject_id=subject_id,
            query=topic_label,
            query_embedding=None,
            reranker=None,
            limit=max(count * 2, 5),
            merge_hierarchy=False,
        )
        notes_context = "\n".join(item.result.text for item in result.items)
        messages = build_flashcard_prompt(topic_label, notes_context, count)
        response = await self._router.complete(
            messages, agent_id=self.AGENT_ID, prompt_version=self._prompt_version
        )
        if response.failed:
            msg = f"flashcard router exhausted: {response.failure_reason}"
            raise FlashcardGenerationError(msg)
        return parse_flashcards(response.content)


@dataclass(frozen=True)
class TopicPerformance:
    topic_label: str
    accuracy: float  # fraction of reviews rated Good/Easy, in [0, 1]


def weighted_topic_selection(
    performances: list[TopicPerformance], total_slots: int
) -> dict[str, int]:
    """Allocate `total_slots` questions/cards across topics, weighting poor performers higher.

    Weight is `1 - accuracy` (floored at a small epsilon so a perfect topic
    still gets a token presence rather than zero, avoiding it vanishing
    from a review set entirely). Topics performed worst on receive
    proportionally more slots (T58.4/FR-7.5).
    """
    if not performances or total_slots <= 0:
        return {}
    epsilon = 0.05
    weights = {p.topic_label: max(1.0 - p.accuracy, epsilon) for p in performances}
    total_weight = sum(weights.values())

    raw = {label: (w / total_weight) * total_slots for label, w in weights.items()}
    allocation = {label: int(v) for label, v in raw.items()}
    remainder = total_slots - sum(allocation.values())

    # Distribute leftover slots (from flooring) to the largest fractional
    # remainders first, so `total_slots` is always fully allocated.
    fractional = sorted(raw.items(), key=lambda kv: kv[1] - int(kv[1]), reverse=True)
    for label, _ in fractional[:remainder]:
        allocation[label] += 1
    return allocation


def group_reviews_by_topic(
    reviews: list[tuple[str, bool]],
) -> list[TopicPerformance]:
    """`reviews` is (topic_label, was_correct) pairs -> per-topic accuracy."""
    correct: dict[str, int] = defaultdict(int)
    total: dict[str, int] = defaultdict(int)
    for topic_label, was_correct in reviews:
        total[topic_label] += 1
        if was_correct:
            correct[topic_label] += 1
    return [
        TopicPerformance(topic_label=label, accuracy=correct[label] / total[label])
        for label in total
    ]
