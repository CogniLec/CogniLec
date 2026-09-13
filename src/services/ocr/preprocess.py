"""S60 — OpenCV/Pillow preprocessing (deskew, perspective correct, de-glare).

Real cv2 operations, exercised for real in tests (T60.4) since
opencv-python-headless runs on CPU with no model weights — unlike the OCR
models themselves (gap #2/#9), preprocessing has no missing-runtime gap.
"""

from __future__ import annotations

from typing import cast

import cv2
import numpy as np
from numpy.typing import NDArray

Image = NDArray[np.uint8]


def _to_gray(image: Image) -> Image:
    if image.ndim == 3:
        return cast(Image, cv2.cvtColor(image, cv2.COLOR_BGR2GRAY))
    return image


def estimate_skew_angle(image: Image) -> float:
    """Estimate the dominant skew angle (degrees) via minAreaRect on text pixels."""
    gray = _to_gray(image)
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    coords = cv2.findNonZero(thresh)
    if coords is None:
        return 0.0
    angle = cv2.minAreaRect(coords)[-1]
    angle = -(90 + angle) if angle < -45 else -angle
    return float(angle)


def deskew(image: Image) -> Image:
    angle = estimate_skew_angle(image)
    if abs(angle) < 0.5:
        return image
    (h, w) = image.shape[:2]
    center = (w // 2, h // 2)
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    return cast(
        Image,
        cv2.warpAffine(
            image, matrix, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
        ),
    )


def deglare(image: Image) -> Image:
    """Reduce glare/hotspots via CLAHE on the luminance channel."""
    gray = _to_gray(image)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return cast(Image, clahe.apply(gray))


def perspective_correct(image: Image) -> Image:
    """Best-effort perspective correction using the largest quadrilateral contour.

    Falls back to the original image when no clean 4-point document edge is
    detected (S60 edge case matrix: "fall back to no correction").
    """
    gray = _to_gray(image)
    edges = cv2.Canny(gray, 50, 150)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return image
    largest = max(contours, key=cv2.contourArea)
    peri = cv2.arcLength(largest, True)
    approx = cv2.approxPolyDP(largest, 0.02 * peri, True)
    if len(approx) != 4:
        return image
    pts = approx.reshape(4, 2).astype(np.float32)
    (h, w) = image.shape[:2]
    dst = np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], dtype=np.float32)
    matrix = cv2.getPerspectiveTransform(pts, dst)
    return cast(Image, cv2.warpPerspective(image, matrix, (w, h)))


def preprocess_image(
    image: Image,
    *,
    enable_deskew: bool = True,
    enable_perspective_correct: bool = True,
    enable_deglare: bool = True,
) -> tuple[Image, list[str]]:
    applied: list[str] = []
    out = image
    if enable_perspective_correct:
        out = perspective_correct(out)
        applied.append("perspective_correct")
    if enable_deskew:
        out = deskew(out)
        applied.append("deskew")
    if enable_deglare:
        out = deglare(out)
        applied.append("deglare")
    return out, applied
