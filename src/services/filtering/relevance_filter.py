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

import asyncio
import json
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, Field, ValidationError
from src.services.llm.router import LLMRouter, inline_schema_refs

# 20 was too large for Machine B's real hardware ceiling: vLLM there reports
# max_model_len=2048 (4GB VRAM card, ADR-015), and a real batch of 20 lecture
# utterances plus the system/topic prompt can exceed that -- confirmed live,
# this was part of what made real S41 batches slow/fail even after raising
# LiteLLM's timeout (docs/gaps.md #33a). Smaller batches fit reliably within
# the context ceiling; the trade-off is more LLM calls per session.
DEFAULT_BATCH_SIZE = 8

# Batches were previously processed strictly sequentially, one at a time --
# each one waiting for the last to finish even though classify_session's own
# docstring says batches are independent (no state carries across them).
#
# First attempt at concurrency=2 against a SINGLE backend (Machine B's one
# 4GB GPU) made things WORSE, not better -- confirmed live: two concurrent
# guided_json requests contended for the same scarce GPU, producing an
# incomplete decision array and then two full-length (240s) timeouts where
# the sequential path succeeded outright. Reverted to 1 at that point.
#
# Re-raised to 2 after standing up a genuine second Tier-1 backend
# (config/litellm.yaml now has two `tier_1_local` entries on two separate
# GPUs, load-balanced by LiteLLM itself -- see docs/gaps.md #33c) -- with
# two real backends instead of one, concurrent requests can now land on
# different hardware instead of contending for the same card. Still not
# safe to assume higher than 2 without more real backends behind LiteLLM;
# a caller should only raise this alongside actually adding more capacity,
# not on faith.
DEFAULT_MAX_CONCURRENCY = 2

# Per-batch attempts before giving up on a batch (see _classify_batch).
MAX_BATCH_ATTEMPTS = 3


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


# Passed to LLMRouter.complete() as `guided_json` so a Tier-1 vLLM call is
# constrained to emit exactly this shape -- confirmed live: without this,
# the small quantized Tier-1 model intermittently produced malformed
# decisions (empty filter_reason, missing confidence field, filter_reason
# over the 100-char limit) that parse_decisions() then rejected outright,
# burning Prefect retries and sometimes exhausting them (docs/gaps.md #33).
_DECISIONS_SCHEMA: dict[str, object] = {
    "type": "array",
    "items": inline_schema_refs(RelevanceDecision.model_json_schema()),
}


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


def parse_partial_decisions(raw: str, expected_seqs: set[int]) -> list[RelevanceDecision]:
    """Lenient parse: keep every valid decision whose seq was asked for.

    Unlike `parse_decisions`, a missing/duplicate/malformed item does not
    invalidate the rest -- the caller re-asks only for what's absent.
    """
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        msg = f"non-JSON A1 response: {exc}"
        raise RelevanceFilterError(msg) from exc
    if not isinstance(payload, list):
        msg = "A1 response must be a JSON array"
        raise RelevanceFilterError(msg)

    decisions: dict[int, RelevanceDecision] = {}
    for item in payload:
        try:
            decision = RelevanceDecision.model_validate(item)
        except ValidationError:
            continue
        if decision.seq in expected_seqs:
            decisions.setdefault(decision.seq, decision)
    return list(decisions.values())


class RelevanceFilterAgent:
    """A1 — batched relevance classification against S37's router."""

    AGENT_ID = "A1_RELEVANCE_FILTER"

    def __init__(
        self,
        router: LLMRouter,
        prompt_version: str = "v1.0.0",
        batch_size: int = DEFAULT_BATCH_SIZE,
        max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
    ) -> None:
        self._router = router
        self._prompt_version = prompt_version
        self._batch_size = batch_size
        self._max_concurrency = max_concurrency

    async def _classify_batch(
        self, topic_label: str, batch: list[UtteranceInput]
    ) -> list[RelevanceDecision]:
        """Classify one batch, retrying ONLY what's missing.

        The small Tier-1 model regularly returns a decision list that omits
        one utterance (confirmed live on a real 10-minute recording: "A1
        decisions cover [...7 of 8...]"). Previously that raised for the whole
        batch, failing the whole T5 task, and Prefect's task-level retry then
        re-ran ALL batches (28 for 10 minutes, ~170 for an hour) -- so one
        omission anywhere discarded every other batch's finished work.
        Now valid decisions are kept and only the utterances still missing
        are re-asked, so a flaky omission costs one small extra call.
        """
        decisions: dict[int, RelevanceDecision] = {}
        remaining = batch
        last_error = "no attempts made"
        for _ in range(MAX_BATCH_ATTEMPTS):
            messages = build_prompt(topic_label, remaining)
            response = await self._router.complete(
                messages,
                agent_id=self.AGENT_ID,
                prompt_version=self._prompt_version,
                schema=_DECISIONS_SCHEMA,
            )
            if response.failed:
                last_error = f"A1 router exhausted: {response.failure_reason}"
                continue
            try:
                got = parse_partial_decisions(response.content, {u.seq for u in remaining})
            except RelevanceFilterError as exc:
                last_error = str(exc)
                continue
            decisions.update({d.seq: d for d in got})
            remaining = [u for u in batch if u.seq not in decisions]
            if not remaining:
                return [decisions[u.seq] for u in batch]
            last_error = f"A1 decisions missing seqs {[u.seq for u in remaining]}"
        raise RelevanceFilterError(last_error)

    async def classify_session(
        self, topic_label: str, utterances: list[UtteranceInput]
    ) -> list[RelevanceDecision]:
        """Classify every utterance. Batch boundaries never change a decision

        (T41.6) because each batch is scored independently against the same
        fixed topic label and each utterance's own text/outlier_score - no
        state carries across batches. That independence is what makes
        bounded-concurrency processing below safe.
        """
        semaphore = asyncio.Semaphore(self._max_concurrency)

        async def bounded(batch: list[UtteranceInput]) -> list[RelevanceDecision]:
            async with semaphore:
                return await self._classify_batch(topic_label, batch)

        batches = batch_utterances(utterances, self._batch_size)
        results = await asyncio.gather(*(bounded(batch) for batch in batches))
        decisions: list[RelevanceDecision] = []
        for batch_decisions in results:
            decisions.extend(batch_decisions)
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
