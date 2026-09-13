"""S61 — Graphviz/DOT diagram generation for graph/network concepts.

No `dot` binary is installed in this sandbox (same disclosed gap as
`mermaid.py` — no system Graphviz package here); `validate()` is a real
DOT-grammar structure check, not a call to `dot -Tsvg`.
"""

from __future__ import annotations

import itertools
import re

from src.services.visual_enrichment.models import DetectedConcept, DiagramFormat, TextDiagram
from src.services.visual_enrichment.text_diagrams.base import DiagramGenerator
from src.services.visual_enrichment.text_diagrams.mermaid import _extract_steps, _slug

_EDGE_RE = re.compile(r"--|->")


class GraphvizGenerator(DiagramGenerator):
    def generate(self, concept: DetectedConcept) -> TextDiagram:
        nodes = _extract_steps(concept.source_text) or [concept.description or "concept"]
        node_ids = [_slug(n) for n in nodes]
        lines = ["digraph G {"]
        for node_id, label in zip(node_ids, nodes, strict=True):
            lines.append(f'  {node_id} [label="{label}"];')
        for a, b in itertools.pairwise(node_ids):
            lines.append(f"  {a} -> {b};")
        lines.append("}")
        syntax = "\n".join(lines)
        is_valid, errors = self.validate(syntax)
        return TextDiagram(
            concept_id=concept.id,
            format=DiagramFormat.GRAPHVIZ,
            syntax=syntax,
            is_valid=is_valid,
            validation_errors=errors,
        )

    def validate(self, syntax: str) -> tuple[bool, list[str]]:
        errors: list[str] = []
        stripped = syntax.strip()
        if not re.match(r"^(strict\s+)?(di)?graph\s+\w*\s*\{", stripped):
            errors.append("missing graph/digraph header")
        if stripped.count("{") != stripped.count("}"):
            errors.append("unbalanced braces")
        return (len(errors) == 0), errors
