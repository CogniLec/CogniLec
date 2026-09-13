"""S62 — attribution formatting for licensed images (T62.5, NFR-S7)."""

from __future__ import annotations

from src.services.image_retrieval.models import ImageAsset


def format_attribution(image: ImageAsset, title: str) -> str:
    author = image.author or "Unknown author"
    licence_label = image.licence.value.upper().replace("-", " ")
    return f"{title} by {author}, licensed under {licence_label}"
