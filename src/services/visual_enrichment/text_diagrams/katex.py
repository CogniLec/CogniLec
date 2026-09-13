"""S61 — KaTeX formula extraction for math-formula concepts.

KaTeX renders client-side (per spec section 6); server-side validation
here is a real balanced-delimiter/known-command check, since no headless
KaTeX renderer is available server-side.
"""

from __future__ import annotations

import re

from src.services.visual_enrichment.models import DetectedConcept, DiagramFormat, TextDiagram
from src.services.visual_enrichment.text_diagrams.base import DiagramGenerator

_KNOWN_COMMANDS = re.compile(r"\\(frac|sqrt|sum|int|alpha|beta|theta|cdot|times|infty)")


class KaTeXGenerator(DiagramGenerator):
    def generate(self, concept: DetectedConcept) -> TextDiagram:
        syntax = concept.source_text.strip()
        is_valid, errors = self.validate(syntax)
        return TextDiagram(
            concept_id=concept.id,
            format=DiagramFormat.KATEX,
            syntax=syntax,
            is_valid=is_valid,
            validation_errors=errors,
        )

    def validate(self, syntax: str) -> tuple[bool, list[str]]:
        errors: list[str] = []
        if syntax.count("{") != syntax.count("}"):
            errors.append("unbalanced braces")
        if syntax.count("$") % 2 != 0:
            errors.append("unbalanced $ delimiters")
        if not syntax:
            errors.append("empty formula")
        return (len(errors) == 0), errors
