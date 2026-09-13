"""S61 — routes detected concepts to text diagrams first, image path second (D-25)."""

from __future__ import annotations

import uuid

from src.services.visual_enrichment.concept_detector import ConceptDetector, is_text_representable
from src.services.visual_enrichment.models import (
    ConceptDetectionResult,
    ConceptType,
    DiagramFormat,
)
from src.services.visual_enrichment.text_diagrams.base import DiagramGenerator
from src.services.visual_enrichment.text_diagrams.graphviz import GraphvizGenerator
from src.services.visual_enrichment.text_diagrams.katex import KaTeXGenerator
from src.services.visual_enrichment.text_diagrams.mermaid import MermaidGenerator

_GENERATORS: dict[DiagramFormat, DiagramGenerator] = {
    DiagramFormat.MERMAID: MermaidGenerator(),
    DiagramFormat.GRAPHVIZ: GraphvizGenerator(),
    DiagramFormat.KATEX: KaTeXGenerator(),
}


class VisualEnrichmentService:
    def __init__(self) -> None:
        self._detector = ConceptDetector()

    def detect_and_resolve(
        self, note_section_id: uuid.UUID, section_text: str
    ) -> ConceptDetectionResult:
        concepts = self._detector.detect(note_section_id, section_text)
        diagrams = []
        routed_to_image = []

        for concept in concepts:
            if concept.concept_type == ConceptType.GENUINELY_PICTORIAL:
                routed_to_image.append(concept)
                continue
            if not is_text_representable(concept.concept_type):
                continue
            generator = _GENERATORS.get(concept.diagram_format) if concept.diagram_format else None
            if generator is None:
                routed_to_image.append(concept)
                continue
            diagrams.append(generator.generate(concept))

        total = len(concepts)
        text_resolved = len(diagrams)
        image_routed = len(routed_to_image)
        ratio = text_resolved / total if total else 0.0

        return ConceptDetectionResult(
            note_section_id=note_section_id,
            concepts_detected=concepts,
            text_diagrams_generated=diagrams,
            concepts_routed_to_image=routed_to_image,
            total_concepts=total,
            text_resolved_count=text_resolved,
            image_routed_count=image_routed,
            text_resolution_ratio=ratio,
        )
