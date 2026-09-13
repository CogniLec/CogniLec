"""S60 — OCR confidence scoring with two-model disagreement (T60.3, T60.6)."""

from __future__ import annotations

import uuid

from src.services.ocr.models import (
    DEFAULT_CONFIDENCE_HIGH,
    DEFAULT_CONFIDENCE_LOW,
    DEFAULT_DISAGREEMENT_THRESHOLD,
    OCRConfidenceLevel,
    OCRResult,
    OCRServiceType,
)


def _level_for(confidence: float) -> OCRConfidenceLevel:
    if confidence >= DEFAULT_CONFIDENCE_HIGH:
        return OCRConfidenceLevel.HIGH
    if confidence >= DEFAULT_CONFIDENCE_LOW:
        return OCRConfidenceLevel.MEDIUM
    return OCRConfidenceLevel.LOW


class ConfidenceScorer:
    def __init__(
        self,
        disagreement_threshold: float = DEFAULT_DISAGREEMENT_THRESHOLD,
        preprocessing_applied: list[str] | None = None,
    ) -> None:
        self._disagreement_threshold = disagreement_threshold
        self._preprocessing_applied = preprocessing_applied or []

    def score(
        self,
        upload_id: uuid.UUID,
        paddle_result: tuple[str, float] | None,
        vlm_result: tuple[str, float] | None,
    ) -> OCRResult:
        if paddle_result is None and vlm_result is None:
            return OCRResult(
                upload_id=upload_id,
                service_used=OCRServiceType.DOTS_OCR,
                extracted_text="",
                confidence=0.0,
                confidence_level=OCRConfidenceLevel.LOW,
                is_low_confidence=True,
                preprocessing_applied=self._preprocessing_applied,
            )

        if paddle_result is None or vlm_result is None:
            text, confidence = paddle_result or vlm_result  # type: ignore[misc]
            service = OCRServiceType.PADDLE_OCR if paddle_result else OCRServiceType.VLM_OCR
            level = _level_for(confidence)
            return OCRResult(
                upload_id=upload_id,
                service_used=service,
                extracted_text=text,
                confidence=confidence,
                confidence_level=level,
                is_low_confidence=level == OCRConfidenceLevel.LOW,
                paddle_text=paddle_result[0] if paddle_result else None,
                vlm_text=vlm_result[0] if vlm_result else None,
                paddle_confidence=paddle_result[1] if paddle_result else None,
                vlm_confidence=vlm_result[1] if vlm_result else None,
                preprocessing_applied=self._preprocessing_applied,
            )

        paddle_text, paddle_conf = paddle_result
        vlm_text, vlm_conf = vlm_result
        diff = abs(paddle_conf - vlm_conf)
        disagreement = diff >= self._disagreement_threshold

        if disagreement:
            confidence = min(paddle_conf, vlm_conf)
            level = OCRConfidenceLevel.DISAGREEMENT
        else:
            confidence = (paddle_conf + vlm_conf) / 2
            level = _level_for(confidence)

        extracted = vlm_text if vlm_conf >= paddle_conf else paddle_text
        service = OCRServiceType.VLM_OCR if vlm_conf >= paddle_conf else OCRServiceType.PADDLE_OCR

        return OCRResult(
            upload_id=upload_id,
            service_used=service,
            extracted_text=extracted,
            confidence=confidence,
            confidence_level=level,
            is_low_confidence=disagreement or level == OCRConfidenceLevel.LOW,
            disagreement_flag=disagreement,
            paddle_text=paddle_text,
            vlm_text=vlm_text,
            paddle_confidence=paddle_conf,
            vlm_confidence=vlm_conf,
            preprocessing_applied=self._preprocessing_applied,
        )
