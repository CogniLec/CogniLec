"""S60 — OCR pipeline: preprocess -> run provider(s) -> confidence score.

The uploaded image itself is persisted by S59's `UploadRepository`
independently of this pipeline's outcome (T60.5) — this module only ever
produces an `OCRResult`, it never deletes or gates the stored asset.
"""

from __future__ import annotations

import uuid

from src.services.ocr.confidence import ConfidenceScorer
from src.services.ocr.models import OCRResult
from src.services.ocr.preprocess import Image, preprocess_image
from src.services.ocr.provider import OCRProvider


async def run_ocr_pipeline(
    upload_id: uuid.UUID,
    image: Image,
    image_bytes_after_preprocess: bytes,
    paddle_provider: OCRProvider,
    vlm_provider: OCRProvider,
) -> OCRResult:
    _, applied = preprocess_image(image)

    paddle_result: tuple[str, float] | None = None
    vlm_result: tuple[str, float] | None = None

    if paddle_provider.is_available():
        try:
            paddle_result = await paddle_provider.run(image_bytes_after_preprocess)
        except Exception:
            paddle_result = None

    if vlm_provider.is_available():
        try:
            vlm_result = await vlm_provider.run(image_bytes_after_preprocess)
        except Exception:
            vlm_result = None

    scorer = ConfidenceScorer(preprocessing_applied=applied)
    return scorer.score(upload_id, paddle_result, vlm_result)
