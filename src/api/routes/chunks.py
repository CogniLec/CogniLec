"""FastAPI router - chunk upload ingestion (S16)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies.auth import get_current_user
from src.api.dependencies.database import get_db_session
from src.api.dependencies.ownership import require_owned_session
from src.api.dependencies.settings import get_app_settings
from src.api.dependencies.valkey import get_valkey_stream
from src.core.config import Settings
from src.db.exceptions import SessionNotFoundError
from src.db.repositories.session_repo import SessionRepository
from src.services.chunk_ingestion import (
    ChunkIngestionService,
    ChunkUploadRequest,
    ChunkUploadResponse,
    SessionNotAcceptingChunksError,
)
from src.services.storage.client import StorageClient
from src.services.valkey_stream import ValkeyStreamProducer

router = APIRouter(prefix="/sessions", tags=["chunks"])


@router.post(
    "/{session_id}/chunks",
    response_model=ChunkUploadResponse,
    status_code=status.HTTP_200_OK,
)
async def upload_chunk(
    session_id: uuid.UUID,
    sequence: int = Form(...),
    timestamp_ms: int = Form(...),
    duration_ms: int = Form(...),
    chunk: UploadFile = File(...),
    db: AsyncSession = Depends(get_db_session),
    stream: ValkeyStreamProducer = Depends(get_valkey_stream),
    settings: Settings = Depends(get_app_settings),
    current_user: dict[str, object] = Depends(get_current_user),
) -> ChunkUploadResponse:
    await require_owned_session(session_id, db, current_user)
    chunk_bytes = await chunk.read()

    max_bytes = settings.CHUNK_MAX_SIZE_MB * 1024 * 1024
    if len(chunk_bytes) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Chunk exceeds max size of {settings.CHUNK_MAX_SIZE_MB}MB",
        )

    request = ChunkUploadRequest(
        session_id=session_id,
        sequence=sequence,
        timestamp_ms=timestamp_ms,
        duration_ms=duration_ms,
    )

    session_repo = SessionRepository(db)
    storage = StorageClient(settings)
    service = ChunkIngestionService(session_repo, storage, stream)

    try:
        return await service.ingest_chunk(request, chunk_bytes)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SessionNotAcceptingChunksError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ConnectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Object storage unreachable: {exc}",
        ) from exc
