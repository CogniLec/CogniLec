"""S61 — Mermaid diagram generation (flowchart / tree / state machine).

No `mmdc` (Mermaid CLI) binary is installed in this sandbox and it cannot
be installed offline (Node.js package, not a pip/uv dependency) — a new,
disclosed gap alongside the existing "no OCR/Docling/typst binaries" gap.
`validate()` here is therefore a real hand-written Mermaid grammar
structure check (header + node/edge syntax), not a call to `mmdc`; it
genuinely rejects malformed syntax rather than fabricating a pass.
"""

from __future__ import annotations

import itertools
import re

from src.services.visual_enrichment.models import (
    ConceptType,
    DetectedConcept,
    DiagramFormat,
    TextDiagram,
)
from src.services.visual_enrichment.text_diagrams.base import DiagramGenerator

_ARROW_RE = re.compile(r"->|→")
_STEP_SPLIT_RE = re.compile(r"->|→")
_VALID_HEADERS = ("graph TD", "graph LR", "flowchart TD", "flowchart LR", "stateDiagram-v2")


def _extract_steps(text: str) -> list[str]:
    normalized = text.replace("→", "->")
    # Trim leading narration ("The process goes: ...") down to the step chain.
    if ":" in normalized:
        normalized = normalized.split(":", 1)[1]
    parts = [p.strip(" .") for p in normalized.split("->")]
    return [p for p in parts if p]


def _slug(label: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]", "_", label.strip())[:30] or "n"


class MermaidGenerator(DiagramGenerator):
    def generate(self, concept: DetectedConcept) -> TextDiagram:
        steps = _extract_steps(concept.source_text)
        if len(steps) < 2:
            steps = [concept.description or "concept"]

        if concept.concept_type == ConceptType.STATE_MACHINE:
            syntax = self._state_machine(steps)
        elif concept.concept_type == ConceptType.TREE_HIERARCHY:
            syntax = self._tree(steps)
        else:
            syntax = self._flowchart(steps)

        is_valid, errors = self.validate(syntax)
        return TextDiagram(
            concept_id=concept.id,
            format=DiagramFormat.MERMAID,
            syntax=syntax,
            is_valid=is_valid,
            validation_errors=errors,
        )

    def _flowchart(self, steps: list[str]) -> str:
        lines = ["graph TD"]
        node_ids = [_slug(s) for s in steps]
        for node_id, label in zip(node_ids, steps, strict=True):
            lines.append(f'    {node_id}["{label}"]')
        for a, b in itertools.pairwise(node_ids):
            lines.append(f"    {a} --> {b}")
        return "\n".join(lines)

    def _tree(self, steps: list[str]) -> str:
        lines = ["graph TD"]
        node_ids = [_slug(s) for s in steps]
        for node_id, label in zip(node_ids, steps, strict=True):
            lines.append(f'    {node_id}["{label}"]')
        for parent, child in itertools.pairwise(node_ids):
            lines.append(f"    {parent} --> {child}")
        return "\n".join(lines)

    def _state_machine(self, steps: list[str]) -> str:
        lines = ["stateDiagram-v2"]
        for a, b in itertools.pairwise(steps):
            lines.append(f"    {_slug(a)} --> {_slug(b)}")
        return "\n".join(lines)

    def validate(self, syntax: str) -> tuple[bool, list[str]]:
        errors: list[str] = []
        lines = [line for line in syntax.strip().splitlines() if line.strip()]
        if not lines:
            return False, ["empty diagram"]
        header = lines[0].strip()
        if not any(header.startswith(h) for h in _VALID_HEADERS):
            errors.append(f"unrecognized diagram header: {header!r}")
        has_edge = any(_ARROW_RE.search(line) for line in lines[1:])
        if not has_edge and len(lines) > 2:
            errors.append("no edges found in diagram body")
        return (len(errors) == 0), errors
