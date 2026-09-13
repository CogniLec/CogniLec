"""S59 — upload processing pipeline: validate -> strip -> dedup -> trigger.

`process_upload` is pure (no I/O beyond the bytes/hashes it's handed) so it
can be unit tested without a database or storage backend; the API route
wires it to real persistence and the S47 `uploads.ready` re-run trigger.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from src.services.uploads.dedup import compute_phash, find_duplicate
from src.services.uploads.exif_strip import strip_exif
from src.services.uploads.models import (
    ALLOWED_IMAGE_TYPES,
    ALLOWED_PDF_TYPES,
    DEFAULT_MAX_FILE_SIZE_BYTES,
    DEFAULT_PHASH_HAMMING_THRESHOLD,
    FileType,
    UploadStatus,
)

RerunTrigger = Callable[[str, list[str]], Awaitable[None]]


class UploadValidationError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def validate_upload(
    content_type: str,
    size_bytes: int,
    max_size_bytes: int = DEFAULT_MAX_FILE_SIZE_BYTES,
) -> FileType:
    if size_bytes > max_size_bytes:
        raise UploadValidationError(
            413, f"File exceeds maximum size of {max_size_bytes // (1024 * 1024)}MB"
        )
    if content_type in ALLOWED_IMAGE_TYPES:
        return FileType.IMAGE
    if content_type in ALLOWED_PDF_TYPES:
        return FileType.PDF
    supported = ", ".join((*ALLOWED_IMAGE_TYPES, *ALLOWED_PDF_TYPES))
    raise UploadValidationError(
        415, f"Unsupported file type '{content_type}'. Supported: {supported}"
    )


@dataclass
class PipelineResult:
    status: UploadStatus
    exif_stripped: bool
    stored_bytes: bytes
    phash: str | None
    is_duplicate: bool
    merged_asset_id: str | None


def run_pipeline(
    *,
    raw_bytes: bytes,
    image_format: str | None,
    file_type: FileType,
    existing_hashes: list[tuple[str, str]],
    phash_threshold: int = DEFAULT_PHASH_HAMMING_THRESHOLD,
) -> PipelineResult:
    """Run strip -> dedup for an already-validated upload.

    PDFs have no EXIF and no pHash-comparable pixel content, so they skip
    straight to `unique` (the edge case matrix explicitly separates PDF
    handling from image EXIF stripping).
    """
    if file_type != FileType.IMAGE:
        return PipelineResult(
            status=UploadStatus.UNIQUE,
            exif_stripped=False,
            stored_bytes=raw_bytes,
            phash=None,
            is_duplicate=False,
            merged_asset_id=None,
        )

    strip_result = strip_exif(raw_bytes, image_format or "PNG")

    try:
        new_hash = compute_phash(strip_result.data)
    except Exception:
        return PipelineResult(
            status=UploadStatus.UNIQUE,
            exif_stripped=strip_result.stripped,
            stored_bytes=strip_result.data,
            phash=None,
            is_duplicate=False,
            merged_asset_id=None,
        )

    duplicate_id = find_duplicate(new_hash, existing_hashes, phash_threshold)
    if duplicate_id is not None:
        return PipelineResult(
            status=UploadStatus.DUPLICATE,
            exif_stripped=strip_result.stripped,
            stored_bytes=strip_result.data,
            phash=new_hash,
            is_duplicate=True,
            merged_asset_id=duplicate_id,
        )

    return PipelineResult(
        status=UploadStatus.UNIQUE,
        exif_stripped=strip_result.stripped,
        stored_bytes=strip_result.data,
        phash=new_hash,
        is_duplicate=False,
        merged_asset_id=None,
    )
