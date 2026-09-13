"""S61 — visual concept detection & text-diagram-first domain models."""

from __future__ import annotations

import uuid
from enum import StrEnum

from pydantic import BaseModel, Field


class ConceptType(StrEnum):
    FLOWCHART = "flowchart"
    TREE_HIERARCHY = "tree"
    STATE_MACHINE = "state_machine"
    SEQUENCE_DIAGRAM = "sequence"
    GRAPH_NETWORK = "graph"
    MATH_FORMULA = "formula"
    TABLE = "table"
    TIMELINE = "timeline"
    CLASS_DIAGRAM = "class_diagram"
    GENUINELY_PICTORIAL = "pictorial"
    UNKNOWN = "unknown"


class DiagramFormat(StrEnum):
    MERMAID = "mermaid"
    GRAPHVIZ = "graphviz"
    D2 = "d2"
    KATEX = "katex"
    MARKDOWN_TABLE = "markdown_table"
    EXCALIDRAW = "excalidraw"


class VisualRoute(StrEnum):
    TEXT_DIAGRAM = "text_diagram"
    LICENSED_IMAGE = "licensed_image"
    AI_GENERATED = "ai_generated"
    SKIPPED = "skipped"


TEXT_REPRESENTABLE_TYPES = {
    ConceptType.FLOWCHART,
    ConceptType.TREE_HIERARCHY,
    ConceptType.STATE_MACHINE,
    ConceptType.SEQUENCE_DIAGRAM,
    ConceptType.GRAPH_NETWORK,
    ConceptType.MATH_FORMULA,
    ConceptType.TABLE,
    ConceptType.TIMELINE,
    ConceptType.CLASS_DIAGRAM,
}

FORMAT_FOR_TYPE: dict[ConceptType, DiagramFormat] = {
    ConceptType.FLOWCHART: DiagramFormat.MERMAID,
    ConceptType.TREE_HIERARCHY: DiagramFormat.MERMAID,
    ConceptType.STATE_MACHINE: DiagramFormat.MERMAID,
    ConceptType.SEQUENCE_DIAGRAM: DiagramFormat.MERMAID,
    ConceptType.TIMELINE: DiagramFormat.MERMAID,
    ConceptType.CLASS_DIAGRAM: DiagramFormat.MERMAID,
    ConceptType.GRAPH_NETWORK: DiagramFormat.GRAPHVIZ,
    ConceptType.MATH_FORMULA: DiagramFormat.KATEX,
    ConceptType.TABLE: DiagramFormat.MARKDOWN_TABLE,
}


class DetectedConcept(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    note_section_id: uuid.UUID
    concept_type: ConceptType
    description: str = Field(..., max_length=2000)
    source_text: str = Field(..., max_length=5000)
    confidence: float = Field(..., ge=0.0, le=1.0)
    route: VisualRoute
    diagram_format: DiagramFormat | None = None


class TextDiagram(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    concept_id: uuid.UUID
    format: DiagramFormat
    syntax: str = Field(..., max_length=10000)
    is_valid: bool = False
    validation_errors: list[str] = Field(default_factory=list)
    render_path: str | None = None


class ConceptDetectionResult(BaseModel):
    note_section_id: uuid.UUID
    concepts_detected: list[DetectedConcept]
    text_diagrams_generated: list[TextDiagram]
    concepts_routed_to_image: list[DetectedConcept]
    total_concepts: int
    text_resolved_count: int
    image_routed_count: int
    text_resolution_ratio: float
