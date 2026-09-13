"""S61 — diagram generator interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.services.visual_enrichment.models import DetectedConcept, TextDiagram


class DiagramGenerator(ABC):
    @abstractmethod
    def generate(self, concept: DetectedConcept) -> TextDiagram:
        """Generate diagram syntax from a detected concept."""

    @abstractmethod
    def validate(self, syntax: str) -> tuple[bool, list[str]]:
        """Validate diagram syntax, returning (is_valid, errors)."""
