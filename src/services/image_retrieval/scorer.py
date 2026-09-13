"""S62 — composite concept-match scoring (§9.4).

composite_score = 0.5 * text_similarity + 0.5 * clip_alignment

No GPU-loaded CLIP model is available in this sandbox (gap #2 — same
underlying constraint as S54's reranker). `CompositeScorer` therefore
takes an injectable `clip_align_fn`; text-similarity uses a real (if
crude) token-overlap Jaccard measure so no component is fabricated, only
the CLIP-alignment component is a caller-supplied stand-in when no CLIP
model is loaded.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from src.services.image_retrieval.licence import LicenceAcceptance, check_licence
from src.services.image_retrieval.models import (
    DEFAULT_SCORE_THRESHOLD,
    RetrievedImage,
    ScoredImage,
)

ClipAlignFn = Callable[[str, RetrievedImage], float]


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def text_similarity(concept_description: str, image_title: str) -> float:
    a, b = _tokenize(concept_description), _tokenize(image_title)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class CompositeScorer:
    def __init__(
        self,
        clip_align_fn: ClipAlignFn,
        threshold: float = DEFAULT_SCORE_THRESHOLD,
    ) -> None:
        self._clip_align_fn = clip_align_fn
        self._threshold = threshold

    def score(self, concept_description: str, image: RetrievedImage) -> ScoredImage | None:
        """Return `None` (no score computed) for a restricted/unverifiable licence.

        Licence check runs before any scoring (T63.4/FR-4.3 ordering) — a
        restricted candidate never reaches `text_similarity`/`clip_align_fn`.
        """
        if check_licence(image.licence) != LicenceAcceptance.ACCEPTED:
            return None

        sim = text_similarity(concept_description, image.title)
        clip = self._clip_align_fn(concept_description, image)
        composite = 0.5 * sim + 0.5 * clip
        return ScoredImage(
            retrieved=image,
            text_similarity=sim,
            clip_alignment=clip,
            composite_score=composite,
            accepted=composite >= self._threshold,
        )
