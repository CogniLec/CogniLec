"""S44 — A2 note synthesis: full-session-context note generation.

A2 receives the full transcript, all segments, prior session notes and
syllabus context (v2.0 SS3.2) rather than segment-by-segment, for
cross-segment coherence -- but "full transcript" is chunked internally
(see MAX_UTTERANCES_PER_CHUNK) rather than sent as one LLM call. The
original single-call design structurally could not complete once a
session's relevant-utterance count exceeded the deployed model's context
window (confirmed via token-budget arithmetic, docs/audit/
pipeline-overhaul.md: roughly 45 relevant utterances, ~13 minutes of real
lecture content) -- it wasn't just slow past that point, it produced zero
notes. Chunking keeps cross-segment coherence within each chunk while
letting a long session simply make more calls instead of one that cannot
fit. It is prompted to prefer Mermaid/KaTeX markup over requesting a
generated image (v1.1 SS20, D-25). Every emitted section must carry
provenance utterance IDs (FR-7.8), and only utterances already marked
`is_relevant=true` may ever be cited or referenced (T44.8/T44.3).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from pydantic import BaseModel, Field, ValidationError
from src.services.llm.router import LLMRouter, inline_schema_refs

logger = logging.getLogger(__name__)

MERMAID_FENCE_RE = re.compile(r"```mermaid\s*\n(.*?)```", re.DOTALL)


@dataclass(frozen=True)
class RelevantUtterance:
    """An utterance eligible for citation - already filtered by A1 (S41)."""

    id: str
    seq: int
    text: str


@dataclass(frozen=True)
class SessionSynthesisContext:
    session_id: str
    utterances: list[RelevantUtterance]
    segment_summaries: list[str] = field(default_factory=list)
    prior_notes_md: list[str] = field(default_factory=list)
    syllabus_context: str = ""


class NoteSectionOutput(BaseModel):
    heading: str = Field(min_length=1, max_length=500)
    body_md: str = Field(min_length=1)
    depth: int = Field(ge=0, le=5)
    ordinal: int = Field(ge=0)
    source_utt_ids: list[str] = Field(min_length=1)


class NoteSynthesisError(Exception):
    """Raised when A2's output fails structural or provenance validation."""


# Passed to LLMRouter.complete() as `guided_json` -- confirmed live: without
# this, A2 (unlike A1's smaller batches) intermittently returned genuinely
# non-JSON output ("Invalid control character", "Expecting value") on the
# large full-transcript prompt, exhausting Prefect's retries entirely on a
# real 5-minute session (docs/gaps.md #33/#33a).
_SECTIONS_SCHEMA: dict[str, object] = {
    "type": "array",
    "items": inline_schema_refs(NoteSectionOutput.model_json_schema()),
}

# Keeps each A2 call within the deployed model's context window. Confirmed
# via direct token-budget arithmetic (docs/audit/pipeline-overhaul.md):
# the original full-transcript-in-one-call design (v2.0 SS3.2) doesn't
# just get slow on a long session, it structurally CANNOT complete past
# roughly 45 relevant utterances (~13 minutes of real lecture at the
# measured 8.67 utt/min / 38.5% relevance rate for a real session) --
# the transcript JSON alone exceeds the 2048-token context, leaving no
# room for the model's own output. 25/chunk is deliberately well under
# that ~44.7-utterance theoretical ceiling, to leave real headroom for
# section output rather than sizing to the exact limit.
MAX_UTTERANCES_PER_CHUNK = 25


def _chunk_utterances(
    utterances: list[RelevantUtterance], chunk_size: int
) -> list[list[RelevantUtterance]]:
    return [utterances[i : i + chunk_size] for i in range(0, len(utterances), chunk_size)]


def build_full_context_prompt(context: SessionSynthesisContext) -> list[dict[str, str]]:
    system = (
        "You are A2, the note synthesis agent. You receive the FULL session "
        "transcript, its segments, prior session notes, and syllabus context "
        "in one call - use this to write coherent notes across the whole "
        "session, not segment-by-segment. Prefer Mermaid diagrams and KaTeX "
        "math over requesting an image asset. Every section MUST cite the "
        "utterance IDs it is based on in `source_utt_ids` - only cite IDs "
        "from the provided transcript (already-filtered, on-topic content "
        "only). "
        'Respond with a JSON array of sections: {"heading": str, '
        '"body_md": str (markdown, may include ```mermaid fences and '
        '$...$/$$...$$ KaTeX), "depth": int (0 = top-level), "ordinal": int '
        "(document order, 0-based), "
        '"source_utt_ids": [utterance id, ...]}.'
    )
    payload = {
        "session_id": context.session_id,
        "transcript": [{"id": u.id, "seq": u.seq, "text": u.text} for u in context.utterances],
        "segment_summaries": context.segment_summaries,
        "prior_session_notes": context.prior_notes_md,
        "syllabus_context": context.syllabus_context,
    }
    return [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(payload)}]


def validate_mermaid_blocks(body_md: str) -> bool:
    """Every fenced ```mermaid block must be non-empty (a real diagnostic

    syntax check requires a JS-based parser; this validates the structural
    contract A2 must follow - a well-formed, non-empty fence).
    """
    return all(block.strip() for block in MERMAID_FENCE_RE.findall(body_md))


def validate_katex(body_md: str) -> bool:
    """KaTeX delimiters ($...$ and $$...$$) must be balanced."""
    stripped = body_md.replace("$$", "")
    return stripped.count("$") % 2 == 0


def validate_hierarchy(sections: list[NoteSectionOutput]) -> bool:
    ordinals = [s.ordinal for s in sections]
    return ordinals == sorted(ordinals) and len(set(ordinals)) == len(ordinals)


def parse_sections(raw: str) -> list[NoteSectionOutput]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        msg = f"non-JSON A2 response: {exc}"
        raise NoteSynthesisError(msg) from exc
    if not isinstance(payload, list) or not payload:
        msg = "A2 response must be a non-empty JSON array"
        raise NoteSynthesisError(msg)
    try:
        return [NoteSectionOutput.model_validate(item) for item in payload]
    except ValidationError as exc:
        msg = f"malformed A2 section: {exc}"
        raise NoteSynthesisError(msg) from exc


class NoteSynthesisAgent:
    """A2 — full-context note synthesis against S37's router."""

    AGENT_ID = "A2_NOTE_SYNTHESIS"

    def __init__(self, router: LLMRouter, prompt_version: str = "v1.0.0") -> None:
        self._router = router
        self._prompt_version = prompt_version

    async def synthesize(self, context: SessionSynthesisContext) -> list[NoteSectionOutput]:
        """Synthesizes notes across the full session, chunking the relevant
        utterances so each individual LLM call stays within the model's
        context window (see MAX_UTTERANCES_PER_CHUNK above) -- a session
        long enough to need more than one chunk simply makes more calls,
        rather than the single call structurally failing.
        """
        chunks = _chunk_utterances(context.utterances, MAX_UTTERANCES_PER_CHUNK)
        all_sections: list[NoteSectionOutput] = []
        for chunk in chunks:
            chunk_context = SessionSynthesisContext(
                session_id=context.session_id,
                utterances=chunk,
                segment_summaries=context.segment_summaries,
                prior_notes_md=context.prior_notes_md,
                syllabus_context=context.syllabus_context,
            )
            all_sections.extend(await self._synthesize_chunk(chunk_context))

        if not all_sections:
            msg = "A2 produced no valid sections across any chunk"
            raise NoteSynthesisError(msg)

        # Each chunk's own LLM call restarts its ordinals at 0 -- renumber
        # globally, in chunk order, so document order stays correct once
        # chunks are merged.
        return [section.model_copy(update={"ordinal": i}) for i, section in enumerate(all_sections)]

    async def _synthesize_chunk(self, context: SessionSynthesisContext) -> list[NoteSectionOutput]:
        allowed_ids = {u.id for u in context.utterances}
        messages = build_full_context_prompt(context)
        response = await self._router.complete(
            messages,
            agent_id=self.AGENT_ID,
            prompt_version=self._prompt_version,
            schema=_SECTIONS_SCHEMA,
        )
        if response.failed:
            msg = f"A2 router exhausted: {response.failure_reason}"
            raise NoteSynthesisError(msg)

        sections = parse_sections(response.content)

        if not validate_hierarchy(sections):
            msg = "A2 sections must have unique, sorted ordinals"
            raise NoteSynthesisError(msg)

        # One hallucinated citation used to discard the ENTIRE batch,
        # valid sections included -- confirmed live (docs/gaps.md #33g): a
        # real recording produced 0 flashcards because a single section
        # cited a non-existent utterance ID. Drop only the offending
        # section(s) instead, so the rest of a genuinely good synthesis
        # still survives; only fail outright (in synthesize(), across all
        # chunks) if nothing survives at all.
        valid_sections = []
        for section in sections:
            unknown = set(section.source_utt_ids) - allowed_ids
            if unknown:
                logger.warning(
                    "dropping note section citing unknown utterances",
                    extra={"heading": section.heading, "unknown_ids": list(unknown)},
                )
                continue
            if not validate_mermaid_blocks(section.body_md):
                logger.warning(
                    "dropping note section with an empty mermaid block",
                    extra={"heading": section.heading},
                )
                continue
            if not validate_katex(section.body_md):
                logger.warning(
                    "dropping note section with unbalanced KaTeX",
                    extra={"heading": section.heading},
                )
                continue
            valid_sections.append(section)

        return valid_sections
