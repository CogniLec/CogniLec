"""Tests for S60 - OCR services & confidence (T60.1-T60.6).

T60.1/T60.2 (accuracy on a fixed test set of real printed-page/board-photo
images against a real PaddleOCR/VLM-OCR model) need a GPU-loaded OCR model
this sandbox does not have (gap #2/#9: no GPU-loaded models, no OCR
binaries) — both are honest skips. T60.4 (preprocessing improves accuracy)
IS genuinely run: it uses real OpenCV (opencv-python-headless, CPU-only,
no model weights) to deskew a synthetically rotated image and shows the
skew-angle-estimation error drops after preprocessing, which is a real,
measurable proxy for "preprocessing improves OCR input quality" that does
not require an OCR model at all.
"""

from __future__ import annotations

import uuid

import cv2
import numpy as np
import pytest
from src.services.ocr.confidence import ConfidenceScorer
from src.services.ocr.models import OCRConfidenceLevel
from src.services.ocr.pipeline import run_ocr_pipeline
from src.services.ocr.preprocess import deskew, estimate_skew_angle, preprocess_image
from src.services.ocr.provider import OCRProvider, TransportOCRProvider


def _text_like_image(angle_degrees: float = 0.0) -> np.ndarray:
    img = np.full((200, 400), 255, dtype=np.uint8)
    for y in range(60, 140, 20):
        cv2.line(img, (20, y), (350, y), 0, 4)
    if angle_degrees:
        center = (200, 100)
        matrix = cv2.getRotationMatrix2D(center, angle_degrees, 1.0)
        img = cv2.warpAffine(img, matrix, (400, 200), borderValue=255)
    return img


@pytest.mark.skip(
    reason="T60.1: needs a real PaddleOCR-VL model + a fixed 100-image printed-page "
    "test set with ground truth. No GPU-loaded OCR model is available in this "
    "sandbox (docs/gaps.md gap #2/#9)."
)
def test_t60_1_printed_page_accuracy_above_0_95(): ...


@pytest.mark.skip(
    reason="T60.2: needs a real VLM-OCR model + a fixed 50-image board-photo test "
    "set with ground truth to honestly measure best-effort accuracy. No GPU-loaded "
    "VLM is available in this sandbox (docs/gaps.md gap #2/#9)."
)
def test_t60_2_board_photo_accuracy_measured_honestly(): ...


def test_t60_3_low_confidence_extraction_flagged_not_authoritative():
    scorer = ConfidenceScorer()
    result = scorer.score(uuid.uuid4(), ("blurry text maybe", 0.42), None)
    assert result.is_low_confidence is True
    assert result.confidence_level == OCRConfidenceLevel.LOW
    assert result.extracted_text == "blurry text maybe"


def test_t60_4_preprocessing_measurably_improves_skew_correction():
    skewed = _text_like_image(angle_degrees=8.0)
    angle_before = estimate_skew_angle(skewed)
    assert abs(angle_before) > 2.0

    corrected = deskew(skewed)
    angle_after = estimate_skew_angle(corrected)
    assert abs(angle_after) < abs(angle_before)


def test_t60_4_preprocess_image_reports_applied_steps():
    image = _text_like_image()
    _, applied = preprocess_image(image)
    assert "deskew" in applied
    assert "deglare" in applied
    assert "perspective_correct" in applied


@pytest.mark.asyncio
async def test_t60_5_image_retained_regardless_of_ocr_outcome():
    """OCR failure never gates image persistence — S59's UploadRepository
    always stores the asset; this asserts the OCR pipeline itself never
    raises or signals deletion when both providers fail/empty out."""
    upload_id = uuid.uuid4()
    empty_paddle = TransportOCRProvider(transport=None, name="paddle")
    empty_vlm = TransportOCRProvider(transport=None, name="vlm")
    image = _text_like_image()

    result = await run_ocr_pipeline(upload_id, image, b"stub-bytes", empty_paddle, empty_vlm)

    assert result.confidence == 0.0
    assert result.extracted_text == ""
    assert result.upload_id == upload_id
    # The pipeline never signals "delete the asset" - there is no such
    # field/exception path; the caller (upload_repo) is unaffected by this.


def test_t60_6_disagreement_raises_low_confidence_flag():
    # Diff of 0.35 clears the default 0.3 disagreement threshold; the S60
    # spec's own worked example (0.72 vs 0.45, diff 0.27) sits just under
    # its own stated default threshold, so slightly separated values are
    # used here to unambiguously exercise the disagreement branch.
    scorer = ConfidenceScorer()
    result = scorer.score(
        uuid.uuid4(),
        paddle_result=("Different text from paddle", 0.80),
        vlm_result=("This text may be inaccurate", 0.45),
    )
    assert result.disagreement_flag is True
    assert result.confidence_level == OCRConfidenceLevel.DISAGREEMENT
    assert result.confidence == 0.45
    assert result.paddle_text == "Different text from paddle"
    assert result.vlm_text == "This text may be inaccurate"


def test_t60_6_agreement_does_not_flag_disagreement():
    scorer = ConfidenceScorer()
    result = scorer.score(
        uuid.uuid4(),
        paddle_result=("same text", 0.90),
        vlm_result=("same text", 0.88),
    )
    assert result.disagreement_flag is False
    assert result.confidence_level == OCRConfidenceLevel.HIGH


@pytest.mark.asyncio
async def test_ocr_pipeline_uses_available_provider():
    async def fake_transport(_: bytes) -> tuple[str, float]:
        return ("Gradient descent is an iterative optimization algorithm", 0.92)

    paddle = TransportOCRProvider(transport=fake_transport, name="paddle")
    vlm: OCRProvider = TransportOCRProvider(transport=None, name="vlm")
    image = _text_like_image()

    result = await run_ocr_pipeline(uuid.uuid4(), image, b"stub", paddle, vlm)
    assert result.confidence == 0.92
    assert result.confidence_level == OCRConfidenceLevel.HIGH
    assert "Gradient descent" in result.extracted_text
