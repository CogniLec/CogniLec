"""S59 — EXIF/GPS stripping on upload ingest (T59.2, a privacy requirement).

Pillow's `Image.save` does not copy EXIF unless explicitly told to, so the
default re-encode path already drops it; piexif is kept as an explicit
fallback for the rare image Pillow can decode but not cleanly re-encode
(e.g. some malformed JPEGs) so that stripping never silently no-ops.
"""

from __future__ import annotations

import io
import logging

import piexif
from PIL import Image

logger = logging.getLogger(__name__)


class ExifStripResult:
    def __init__(self, data: bytes, stripped: bool) -> None:
        self.data = data
        self.stripped = stripped


def strip_exif(image_bytes: bytes, image_format: str) -> ExifStripResult:
    """Return image bytes with all EXIF/GPS metadata removed.

    Falls back to storing the original bytes (with `stripped=False`) if the
    image cannot be decoded at all — the edge case matrix in the S59 spec
    requires the upload to still succeed in that case.
    """
    try:
        return _strip_via_pillow(image_bytes, image_format)
    except Exception:
        logger.warning("Pillow EXIF strip failed, trying piexif fallback", exc_info=True)
    try:
        return _strip_via_piexif(image_bytes)
    except Exception:
        logger.warning("piexif EXIF strip fallback also failed", exc_info=True)
        return ExifStripResult(data=image_bytes, stripped=False)


def _strip_via_pillow(image_bytes: bytes, image_format: str) -> ExifStripResult:
    with Image.open(io.BytesIO(image_bytes)) as img:
        img.load()
        clean = Image.new(img.mode, img.size)
        clean.putdata(list(img.getdata()))
        out = io.BytesIO()
        clean.save(out, format=image_format)
        return ExifStripResult(data=out.getvalue(), stripped=True)


def _strip_via_piexif(image_bytes: bytes) -> ExifStripResult:
    stripped = piexif.remove(image_bytes)
    return ExifStripResult(data=stripped, stripped=True)


def has_exif(image_bytes: bytes) -> bool:
    """Check whether any EXIF segment (including GPS IFD) remains."""
    try:
        exif_dict = piexif.load(image_bytes)
    except Exception:
        return False
    return any(exif_dict.get(ifd) for ifd in ("0th", "Exif", "GPS", "1st"))
