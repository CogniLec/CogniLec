"""S31 — LLM-generated topic labels from top-N representative utterances + keywords.

Uses whatever LLM client is handed in (the S37 `LLMRouter` satisfies this
duck-typed `complete(prompt) -> str` interface) so labelling degrades
gracefully rather than hard-depending on Block 6 wiring.
"""

from __future__ import annotations

import logging
import uuid
from typing import Protocol

log = logging.getLogger(__name__)

LABELLING_PROMPT_V1 = """You are given a topic cluster from a university lecture transcript.

Top representative utterances:
{utterances}

Top keywords: {keywords}

Generate a short, descriptive label (max 10 words) for this topic.
The label should be specific enough to distinguish it from other topics in the same subject.

Label:"""


class LabellingLLMClient(Protocol):
    async def complete(self, prompt: str) -> str: ...


def _placeholder_label(topic_id: uuid.UUID) -> str:
    return f"Topic {str(topic_id)[:8]}"


async def generate_topic_label(
    topic_id: uuid.UUID,
    utterances: list[str],
    keywords: list[str],
    llm_client: LabellingLLMClient,
    prompt_version: str = "v1",
) -> str:
    """Generate a topic label using an LLM from top-N utterances and keywords.

    Falls back to a placeholder label on any LLM failure or empty response
    (S31 §6.5) - a labelling failure must never break the pipeline.
    """
    prompt = LABELLING_PROMPT_V1.format(
        utterances="\n".join(f"- {u}" for u in utterances), keywords=", ".join(keywords)
    )

    for attempt in range(2):
        try:
            label = await llm_client.complete(prompt)
        except Exception as exc:
            log.warning("labelling.placeholder_used: LLM failure on attempt %d: %s", attempt, exc)
            continue

        label = (label or "").strip()
        if label:
            return label
        log.warning("labelling.placeholder_used: empty label on attempt %d", attempt)

    log.warning("labelling.placeholder_used: topic_id=%s", topic_id)
    return _placeholder_label(topic_id)
