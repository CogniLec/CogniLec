"""Audio file upload endpoint — accepts audio files and feeds them into the pipeline."""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies.auth import get_current_user, get_db_session_with_rls
from src.api.dependencies.ownership import require_owned_session
from src.api.dependencies.settings import get_app_settings
from src.api.dependencies.valkey import get_valkey_stream
from src.api.schemas.audio_upload import AudioFileUploadResponse
from src.core.config import Settings
from src.db.repositories.session_repo import SessionRepository
from src.services.audio_file_ingestion import (
    ALLOWED_AUDIO_EXTENSIONS,
    AudioFileIngestionError,
    AudioFileIngestionService,
)
from src.services.chunk_ingestion import ChunkIngestionService
from src.services.storage.client import StorageClient
from src.services.valkey_stream import ValkeyStreamProducer

router = APIRouter(prefix="/sessions", tags=["audio-upload"])

MAX_AUDIO_FILE_SIZE_MB = 200


@router.post(
    "/{session_id}/audio-file",
    response_model=AudioFileUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_audio_file(
    session_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db_session_with_rls),
    stream: ValkeyStreamProducer = Depends(get_valkey_stream),
    settings: Settings = Depends(get_app_settings),
    current_user: dict[str, object] = Depends(get_current_user),
) -> AudioFileUploadResponse:
    """Upload an audio file (MP3, WAV, M4A, FLAC, OGG, WebM) for processing.

    The file is split into 30-second chunks and fed into the existing
    preprocessing → ASR pipeline. The session transitions through
    CREATED → RECORDING → TRANSCRIBED → COMPLETE as chunks are processed.
    """
    await require_owned_session(session_id, db, current_user)

    # Validate file extension
    filename = file.filename or "upload"
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_AUDIO_EXTENSIONS:
        supported = ", ".join(sorted(ALLOWED_AUDIO_EXTENSIONS))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported audio format: {ext}. Supported: {supported}",
        )

    # Read and validate file size
    audio_bytes = await file.read()
    max_bytes = MAX_AUDIO_FILE_SIZE_MB * 1024 * 1024
    if len(audio_bytes) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Audio file exceeds max size of {MAX_AUDIO_FILE_SIZE_MB}MB",
        )
    if len(audio_bytes) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty",
        )

    # Set up services
    session_repo = SessionRepository(db)
    storage = StorageClient(settings)
    chunk_ingestion = ChunkIngestionService(session_repo, storage, stream)
    ingestion_service = AudioFileIngestionService(chunk_ingestion, storage)

    try:
        result = await ingestion_service.ingest_audio_file(
            session_id=session_id,
            filename=filename,
            audio_bytes=audio_bytes,
        )
    except (ValueError, AudioFileIngestionError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process audio file: {exc}",
        ) from exc
    except ConnectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Object storage unreachable: {exc}",
        ) from exc

    duration_s = result.duration_ms // 1000
    chunks = result.total_chunks
    return AudioFileUploadResponse(
        session_id=result.session_id,
        filename=result.filename,
        total_chunks=result.total_chunks,
        status="accepted",
        message=(
            f"Audio file accepted ({duration_s}s, {chunks} chunks). Processing will begin shortly."
        ),
    )
