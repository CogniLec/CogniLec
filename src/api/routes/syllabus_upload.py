"""S51 — syllabus document upload endpoint.

Mounted under ``/subjects/{subject_id}/syllabus`` (see
``src.api.routes.subjects``) so it is part of the subject-creation flow
rather than a generic settings page, per spec section 12.5.
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies.auth import get_current_user, get_db_session_with_rls
from src.api.dependencies.database import get_syllabus_db_session
from src.api.dependencies.ownership import require_owned_subject
from src.api.schemas.syllabus_upload import SyllabusUploadResponse
from src.db.repositories.syllabus_repo import SyllabusRepository
from src.services.syllabus.upload_pipeline import SyllabusUploadPipeline

router = APIRouter(prefix="/subjects", tags=["syllabus-upload"])

MAX_UPLOAD_SIZE_BYTES = 20 * 1024 * 1024


@router.post(
    "/{subject_id}/syllabus",
    response_model=SyllabusUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_syllabus(
    subject_id: uuid.UUID,
    file: UploadFile,
    db: AsyncSession = Depends(get_syllabus_db_session),
    main_db: AsyncSession = Depends(get_db_session_with_rls),
    current_user: dict[str, object] = Depends(get_current_user),
) -> SyllabusUploadResponse:
    await require_owned_subject(subject_id, main_db, current_user)

    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds max size of {MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)}MB",
        )

    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename or "").suffix) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        repo = SyllabusRepository(db)
        pipeline = SyllabusUploadPipeline(repo)
        return await pipeline.process(subject_id, tmp_path, file.filename or "upload")
    finally:
        tmp_path.unlink(missing_ok=True)
