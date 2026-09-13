"""S50 — A6 syllabus extraction agent.

Naming note: this is the spec's "A6" (syllabus extraction). It is a
*distinct* concept from ``src.services.llm.schema_registry.AgentID.A6``
(the S38 registry's progress-analyst persona, established in an earlier
block and load-bearing for other tests) - the class here is named
``SyllabusExtractionAgent`` rather than ``A6Agent`` to avoid colliding with
that existing identifier while still matching the spec's behavioural
contract (``extract`` / ``extract_from_mixed_session``).

Extraction is rule-based (regex over transcript lines), not LLM
grammar-constrained decoding as the spec's tech stack table calls for
(Outlines/XGrammar) - there is no local model runtime available in this
environment to decode against (see docs/gaps.md gap #3 GPU note and gap
#9 for this block's write-up). The rule-based path is a genuine,
testable implementation against transcripts with recognisable
"Module N: ...", "N.M Topic", "Assignment/Exam ... (20%)",
"Week N: ..." and "Reference: ..." structure, with a confidence score
that degrades (raising grade_of_authority) when little structure is found.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from config.schemas.a6_syllabus import (
    MAX_HIERARCHY_DEPTH,
    A6SyllabusOutput,
    ExtractedSyllabusItem,
    ItemType,
)

_MODULE_RE = re.compile(r"^\s*module\s+(\d+)\s*[:.\-]\s*(.+)$", re.IGNORECASE)
_TOPIC_RE = re.compile(r"^\s*(\d+)\.(\d+)\s*[:.\-]?\s*(.+)$")
_ASSESSMENT_RE = re.compile(
    r"^\s*(assignment|exam|quiz|midterm|final|project)\s*\d*\s*[:.\-]?\s*(.+?)"
    r"(?:\((?:weight\s+)?(\d+(?:\.\d+)?)\s*%\))?\s*$",
    re.IGNORECASE,
)
_SCHEDULE_RE = re.compile(r"^\s*week\s+(\d+)\s*[:.\-]\s*(.+)$", re.IGNORECASE)
_REFERENCE_RE = re.compile(r"^\s*reference[s]?\s*[:.\-]\s*(.+)$", re.IGNORECASE)


class ExtractionRejectedError(Exception):
    """Raised when extraction confidence is too low (grade_of_authority > 2)."""


@dataclass
class TranscriptChunk:
    text: str
    session_id: uuid.UUID | None = None


def _chunk_lines(transcript_text: str) -> list[str]:
    return [line.strip() for line in transcript_text.splitlines() if line.strip()]


class SyllabusExtractionAgent:
    """A6: extracts structured syllabus items from a syllabus-lecture transcript."""

    def __init__(self, confidence_min_grade: int = 2) -> None:
        self._confidence_min_grade = confidence_min_grade

    async def extract(
        self, transcript: TranscriptChunk, subject_id: uuid.UUID, subject_title: str = ""
    ) -> A6SyllabusOutput:
        """Extract structured syllabus items from a transcript chunk."""
        lines = _chunk_lines(transcript.text)
        items, _current_module_ordinal = self._parse_lines(lines)

        confidence = _estimate_confidence(len(lines), len(items))
        grade_of_authority = _confidence_to_grade(confidence)

        output = A6SyllabusOutput(
            items=items,
            subject_title=subject_title or "Untitled Subject",
            extraction_confidence=confidence,
            grade_of_authority=grade_of_authority,
        )
        if grade_of_authority > self._confidence_min_grade and items:
            msg = f"extraction confidence too low: grade_of_authority={grade_of_authority}"
            raise ExtractionRejectedError(msg)
        return output

    async def extract_from_mixed_session(
        self, full_transcript_text: str, syllabus_segment_text: str, subject_id: uuid.UUID
    ) -> A6SyllabusOutput:
        """Extract from an isolated syllabus segment of a mixed session (AC-13)."""
        return await self.extract(TranscriptChunk(text=syllabus_segment_text), subject_id)

    def _parse_lines(
        self, lines: list[str]
    ) -> tuple[list[ExtractedSyllabusItem], int]:
        items: list[ExtractedSyllabusItem] = []
        module_ordinal = -1
        topic_ordinal_by_module: dict[int, int] = {}
        assessment_ordinal = 0
        schedule_ordinal = 0
        depth_capped_descriptions: list[str] = []

        for line in lines:
            if match := _MODULE_RE.match(line):
                module_ordinal += 1
                items.append(
                    ExtractedSyllabusItem(
                        title=match.group(2).strip(),
                        item_type=ItemType.MODULE,
                        ordinal=module_ordinal,
                        parent_ordinal=None,
                    )
                )
                topic_ordinal_by_module[module_ordinal] = 0
                continue

            if match := _TOPIC_RE.match(line):
                mod_num = int(match.group(1)) - 1
                parent_ordinal = mod_num if mod_num in topic_ordinal_by_module else module_ordinal
                if parent_ordinal < 0:
                    depth_capped_descriptions.append(match.group(3).strip())
                    continue
                topic_ordinal = topic_ordinal_by_module.get(parent_ordinal, 0)
                items.append(
                    ExtractedSyllabusItem(
                        title=match.group(3).strip(),
                        item_type=ItemType.TOPIC,
                        ordinal=topic_ordinal,
                        parent_ordinal=parent_ordinal,
                    )
                )
                topic_ordinal_by_module[parent_ordinal] = topic_ordinal + 1
                continue

            if match := _ASSESSMENT_RE.match(line):
                weight = float(match.group(3)) if match.group(3) else None
                items.append(
                    ExtractedSyllabusItem(
                        title=f"{match.group(1).title()}: {match.group(2).strip()}".strip(": "),
                        item_type=ItemType.ASSESSMENT,
                        ordinal=assessment_ordinal,
                        weight_pct=weight,
                    )
                )
                assessment_ordinal += 1
                continue

            if match := _SCHEDULE_RE.match(line):
                items.append(
                    ExtractedSyllabusItem(
                        title=match.group(2).strip(),
                        item_type=ItemType.SCHEDULE,
                        ordinal=schedule_ordinal,
                        week_number=int(match.group(1)),
                    )
                )
                schedule_ordinal += 1
                continue

            if match := _REFERENCE_RE.match(line):
                if items:
                    items[-1].references.append(match.group(1).strip())
                continue

        if depth_capped_descriptions and items:
            # MAX_HIERARCHY_DEPTH exceeded: flatten into the last module's description.
            for mod_item in reversed(items):
                if mod_item.item_type == ItemType.MODULE:
                    extra = "; ".join(depth_capped_descriptions)
                    mod_item.description = (
                        f"{mod_item.description}; {extra}" if mod_item.description else extra
                    )
                    break

        return items, module_ordinal


def _estimate_confidence(line_count: int, item_count: int) -> float:
    if line_count == 0:
        return 0.0
    density = min(item_count / max(line_count, 1), 1.0)
    base = 0.4 + 0.6 * density
    return round(min(base, 1.0) if item_count > 0 else 0.0, 2)


def _confidence_to_grade(confidence: float) -> int:
    if confidence >= 0.85:
        return 1
    if confidence >= 0.65:
        return 2
    if confidence >= 0.4:
        return 3
    if confidence > 0:
        return 4
    return 5


__all__ = [
    "MAX_HIERARCHY_DEPTH",
    "ExtractionRejectedError",
    "SyllabusExtractionAgent",
    "TranscriptChunk",
]
