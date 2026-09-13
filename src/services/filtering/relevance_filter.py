"""S41 — A1 relevance filter: batched on/off-topic classification.

Filters utterances against the session's identified topic (S30/S32). The
HDBSCAN outlier score (S28) is passed to the LLM as one input feature among
several - never as a hard gate (ADR-011's pre-filter gate is retired now
that GPU tiers remove the cost pressure that motivated it, v2.0 SS3.3).

Decisions are soft-delete only: `is_relevant` + `filter_reason` are written
per utterance, never a row deletion (FR-2.15). Filtering logic makes no
distinction between lecturer and student speaker tags (FR-2.14) - the
prompt is never given `speaker_tag` as a signal to condition on.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, Field, ValidationError
from src.services.llm.router import LLMRouter

DEFAULT_BATCH_SIZE = 20


class FilterCategory(StrEnum):
    CORE_CONTENT = "core_content"
    STUDENT_QUESTION = "student_question"
    ADMIN = "admin"
    ASIDE = "aside"
    TANGENT = "tangent"


@dataclass(frozen=True)
class UtteranceInput:
    """The subset of an utterance's fields A1 needs, keyed by `seq`."""

    seq: int
    text: str
    outlier_score: float | None = None


class RelevanceDecision(BaseModel):
    seq: int
    is_relevant: bool
    category: FilterCategory
    filter_reason: str = Field(min_length=1, max_length=100)
    confidence: float = Field(ge=0.0, le=1.0)


class RelevanceFilterError(Exception):
    """Raised when the LLM response can't be parsed into decisions for the batch."""


def batch_utterances(
    utterances: list[UtteranceInput], batch_size: int = DEFAULT_BATCH_SIZE
) -> list[list[UtteranceInput]]:
    return [utterances[i : i + batch_size] for i in range(0, len(utterances), batch_size)]


def build_prompt(topic_label: str, batch: list[UtteranceInput]) -> list[dict[str, str]]:
    items = [{"seq": u.seq, "text": u.text, "outlier_score": u.outlier_score} for u in batch]
    system = (
        "You are A1, the relevance filter for a lecture note-taking system. "
        "Classify each utterance as on-topic or off-topic against the given "
        "lecture topic. outlier_score (0-1, higher = more embedding-distance "
        "outlier) is one input signal, not a rule - use judgement, not a "
        "threshold on it. Filtering is symmetric: apply the same standard "
        "to lecturer speech and student speech. Off-topic examples: admin "
        "announcements, tangential asides, unrelated small talk. On-topic "
        "examples: core explanations AND student questions about the "
        "topic (a relevant question is never discarded). "
        "Respond with a JSON array, one object per utterance: "
        '{"seq": int, "is_relevant": bool, "category": one of '
        '"core_content"|"student_question"|"admin"|"aside"|"tangent", '
        '"filter_reason": short machine-readable string, "confidence": 0-1}.'
    )
    user = json.dumps({"topic": topic_label, "utterances": items})
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def parse_decisions(raw: str, expected_seqs: set[int]) -> list[RelevanceDecision]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        msg = f"non-JSON A1 response: {exc}"
        raise RelevanceFilterError(msg) from exc

    if not isinstance(payload, list):
        msg = "A1 response must be a JSON array"
        raise RelevanceFilterError(msg)

    decisions: list[RelevanceDecision] = []
    try:
        for item in payload:
            decisions.append(RelevanceDecision.model_validate(item))
    except ValidationError as exc:
        msg = f"malformed A1 decision: {exc}"
        raise RelevanceFilterError(msg) from exc

    got_seqs = {d.seq for d in decisions}
    if got_seqs != expected_seqs:
        msg = f"A1 decisions cover {sorted(got_seqs)}, expected {sorted(expected_seqs)}"
        raise RelevanceFilterError(msg)
    return decisions


class RelevanceFilterAgent:
    """A1 — batched relevance classification against S37's router."""

    AGENT_ID = "A1_RELEVANCE_FILTER"

    def __init__(
        self,
        router: LLMRouter,
        prompt_version: str = "v1.0.0",
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self._router = router
        self._prompt_version = prompt_version
        self._batch_size = batch_size

    async def classify_session(
        self, topic_label: str, utterances: list[UtteranceInput]
    ) -> list[RelevanceDecision]:
        """Classify every utterance. Batch boundaries never change a decision

        (T41.6) because each batch is scored independently against the same
        fixed topic label and each utterance's own text/outlier_score - no
        state carries across batches.
        """
        decisions: list[RelevanceDecision] = []
        for batch in batch_utterances(utterances, self._batch_size):
            messages = build_prompt(topic_label, batch)
            response = await self._router.complete(
                messages, agent_id=self.AGENT_ID, prompt_version=self._prompt_version
            )
            if response.failed:
                msg = f"A1 router exhausted: {response.failure_reason}"
                raise RelevanceFilterError(msg)
            expected = {u.seq for u in batch}
            decisions.extend(parse_decisions(response.content, expected))
        return decisions


def decisions_to_flags(
    decisions: list[RelevanceDecision],
    outlier_scores: dict[int, float | None],
) -> dict[int, tuple[bool, str | None, float | None]]:
    """Shape decisions for `UtteranceRepository.apply_relevance_flags` (S22).

    Preserves each utterance's existing `outlier_score` (S28) unchanged -
    A1 reads it as a feature, it does not recompute or overwrite it.
    """
    return {d.seq: (d.is_relevant, d.filter_reason, outlier_scores.get(d.seq)) for d in decisions}
