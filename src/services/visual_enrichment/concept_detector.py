"""S61 — concept detection (D-25: text-representable diagrams attempted first).

No GPU-loaded LLM is available in this sandbox to run the spec's
`CONCEPT_DETECTION_MODEL` classifier (same class of gap as #2/#9 elsewhere
in this repo), so concept typing here is deterministic keyword/pattern
matching against the exact classification rules the S61 spec itself lists
(section 2, "Concept Detection Rules"). This is a real, testable
simplification — not a fabricated LLM call — and is disclosed as such.
"""

from __future__ import annotations

import re
import uuid

from src.services.visual_enrichment.models import (
    FORMAT_FOR_TYPE,
    TEXT_REPRESENTABLE_TYPES,
    ConceptType,
    DetectedConcept,
    VisualRoute,
)

_PICTORIAL_KEYWORDS = (
    "anatomy",
    "heart",
    "organ",
    "geography",
    "map of",
    "apparatus",
    "microscop",
    "cell structure",
    "skeleton",
    "topograph",
)
_FLOWCHART_KEYWORDS = ("process goes", "the steps are", "→", "->", "then", "followed by")
_HIERARCHY_KEYWORDS = ("hierarchy", "classification", "taxonomy", "is a subclass of")
_STATE_MACHINE_KEYWORDS = ("state transitions", "transitions from", "state machine")
_FORMULA_PATTERN = re.compile(r"[=∑∫√]|\\frac|\bequation\b")
_GRAPH_KEYWORDS = ("network of", "graph of", "connected to", "nodes and edges")


class ConceptDetector:
    """Detects visual-worthy concepts in note section text, D-25 priority order."""

    def detect(self, note_section_id: uuid.UUID, text: str) -> list[DetectedConcept]:
        lowered = text.lower()
        concepts: list[DetectedConcept] = []

        concept_type = self._classify(lowered)
        if concept_type == ConceptType.UNKNOWN:
            return concepts

        route = (
            VisualRoute.LICENSED_IMAGE
            if concept_type == ConceptType.GENUINELY_PICTORIAL
            else VisualRoute.TEXT_DIAGRAM
        )
        concepts.append(
            DetectedConcept(
                note_section_id=note_section_id,
                concept_type=concept_type,
                description=text[:200],
                source_text=text[:2000],
                confidence=0.85,
                route=route,
                diagram_format=FORMAT_FOR_TYPE.get(concept_type),
            )
        )
        return concepts

    def _classify(self, lowered: str) -> ConceptType:
        if any(k in lowered for k in _PICTORIAL_KEYWORDS):
            return ConceptType.GENUINELY_PICTORIAL
        if any(k in lowered for k in _HIERARCHY_KEYWORDS):
            return ConceptType.TREE_HIERARCHY
        if any(k in lowered for k in _STATE_MACHINE_KEYWORDS):
            return ConceptType.STATE_MACHINE
        if _FORMULA_PATTERN.search(lowered):
            return ConceptType.MATH_FORMULA
        if any(k in lowered for k in _GRAPH_KEYWORDS):
            return ConceptType.GRAPH_NETWORK
        if any(k in lowered for k in _FLOWCHART_KEYWORDS):
            return ConceptType.FLOWCHART
        return ConceptType.UNKNOWN


def is_text_representable(concept_type: ConceptType) -> bool:
    return concept_type in TEXT_REPRESENTABLE_TYPES
