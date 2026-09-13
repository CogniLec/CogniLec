"""S59 — post-session upload API (board photos, notes, textbook pages, PDFs).

Not wired into an app instance: no `src/main.py`/FastAPI() app assembly
exists anywhere in this repo yet (checked — every other block's routes are
in the same state), so this router is tested at the service layer
(`src/services/uploads/pipeline.py`) rather than through `TestClient`,
matching the existing convention for `src/api/routes/*` in this codebase.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies.auth import get_db_session_with_rls
from src.api.schemas.upload import UploadResponse
from src.db.repositories.upload_repo import UploadRepository
from src.services.uploads.models import DEFAULT_MAX_FILE_SIZE_BYTES, DEFAULT_PHASH_HAMMING_THRESHOLD
from src.services.uploads.pipeline import UploadValidationError, run_pipeline, validate_upload

router = APIRouter(prefix="/uploads", tags=["uploads"])


@router.post("", response_model=UploadResponse, status_code=201)
async def create_upload(
    file: UploadFile,
    session_id: uuid.UUID,
    subject_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session_with_rls),
) -> UploadResponse:
    raw = await file.read()
    try:
        file_type = validate_upload(file.content_type or "", len(raw), DEFAULT_MAX_FILE_SIZE_BYTES)
    except UploadValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    repo = UploadRepository(db)
    existing_hashes = await repo.get_phashes_for_subject(subject_id)
    result = run_pipeline(
        raw_bytes=raw,
        image_format=(file.content_type or "").split("/")[-1].upper() or None,
        file_type=file_type,
        existing_hashes=existing_hashes,
        phash_threshold=DEFAULT_PHASH_HAMMING_THRESHOLD,
    )
    record = await repo.create_upload(
        session_id=session_id,
        subject_id=subject_id,
        file_type=file_type,
        original_filename=file.filename or "upload",
        stored_bytes=result.stored_bytes,
        status=result.status,
        exif_stripped=result.exif_stripped,
        phash=result.phash,
        merged_asset_id=uuid.UUID(result.merged_asset_id) if result.merged_asset_id else None,
    )
    return UploadResponse.model_validate(record)
