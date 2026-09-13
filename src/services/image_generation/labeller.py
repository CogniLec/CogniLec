"""S63 — AI-generated labelling (AC-17, FR-4.10). Never optional, never False."""

from __future__ import annotations

from src.services.image_generation.schema import GeneratedImage

AI_GENERATED_LABEL = "AI-generated illustration"


def apply_label(image: GeneratedImage) -> GeneratedImage:
    """Return `image` with the AI-generated label guaranteed set.

    `GeneratedImage.is_ai_generated` defaults to `True` and is validated
    to never be `False` (see `schema.py`), so this is idempotent — it
    exists as an explicit step so the pipeline has a named place where the
    label is asserted, per the S63 state machine.
    """
    return image.model_copy(update={"is_ai_generated": True, "ai_label": AI_GENERATED_LABEL})
