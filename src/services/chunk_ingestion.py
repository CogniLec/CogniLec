"""Chunk ingestion domain models and orchestration logic (S16)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, Field
from src.db.models.session import Session, SessionStatus
from src.db.repositories.session_repo import SessionRepository
from src.services.storage.client import StorageClient
from src.services.storage.models import BucketName
from src.services.valkey_stream import ValkeyStreamProducer


class ChunkUploadRequest(BaseModel):
    session_id: UUID
    sequence: int = Field(..., ge=0, description="Chunk sequence number (0-indexed)")
    timestamp_ms: int = Field(..., ge=0, description="Timestamp in ms since session start")
    duration_ms: int = Field(..., gt=0, description="Chunk duration in ms")


class ChunkUploadResponse(BaseModel):
    session_id: UUID
    sequence: int
    stored_key: str
    stream_message_id: str
    status: str  # "stored" | "duplicate"


class StreamMessage(BaseModel):
    event: str = "audio.chunk"
    session_id: UUID
    subject_id: UUID
    sequence: int
    timestamp_ms: int
    duration_ms: int
    object_key: str
    received_at: datetime


class SessionNotAcceptingChunksError(Exception):
    """Raised when a chunk is uploaded for a session in a terminal status."""

    def __init__(self, status: SessionStatus) -> None:
        self.status = status
        super().__init__(f"Session is {status.value}; no more chunks accepted")


_TERMINAL_STATUSES = {SessionStatus.COMPLETE, SessionStatus.FAILED}


def build_object_key(session_id: UUID, sequence: int) -> str:
    """Return the MinIO object key for a chunk: {session_id}/chunks/{seq:05d}.opus."""
    return f"{session_id}/chunks/{sequence:05d}.opus"


def idempotency_key(session_id: UUID, sequence: int) -> str:
    return f"chunk:{session_id}:{sequence}"


class ChunkIngestionService:
    """Orchestrates chunk storage, idempotency, stream publish and status transition."""

    def __init__(
        self,
        session_repo: SessionRepository,
        storage: StorageClient,
        stream: ValkeyStreamProducer,
    ) -> None:
        self._session_repo = session_repo
        self._storage = storage
        self._stream = stream

    async def ingest_chunk(
        self,
        request: ChunkUploadRequest,
        chunk_bytes: bytes,
    ) -> ChunkUploadResponse:
        session_obj = await self._session_repo.get_or_raise(request.session_id)
        if session_obj.status in _TERMINAL_STATUSES:
            raise SessionNotAcceptingChunksError(session_obj.status)

        object_key = build_object_key(request.session_id, request.sequence)
        dedup_key = idempotency_key(request.session_id, request.sequence)

        is_new = await self._stream.set_if_not_exists(dedup_key, "stored", ttl_s=self._stream_ttl())
        if not is_new:
            return ChunkUploadResponse(
                session_id=request.session_id,
                sequence=request.sequence,
                stored_key=object_key,
                stream_message_id="",
                status="duplicate",
            )

        await self._storage.put_object(
            BucketName.AUDIO, object_key, chunk_bytes, content_type="audio/opus"
        )

        # Atomic-with-storage: transition created -> recording on first chunk,
        # before publishing so the SSE status event fires promptly.
        if session_obj.status == SessionStatus.CREATED:
            await self._session_repo.update_status(session_obj, SessionStatus.RECORDING)
            await self._stream.publish_event(
                str(request.session_id),
                "status_changed",
                {
                    "session_id": str(request.session_id),
                    "status": SessionStatus.RECORDING.value,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )

        stream_message = StreamMessage(
            session_id=request.session_id,
            subject_id=session_obj.subject_id,
            sequence=request.sequence,
            timestamp_ms=request.timestamp_ms,
            duration_ms=request.duration_ms,
            object_key=object_key,
            received_at=datetime.now(UTC),
        )
        message_id = await self._stream.xadd_chunk(_stream_fields(stream_message))

        await self._stream.publish_event(
            str(request.session_id),
            "chunk_received",
            {
                "session_id": str(request.session_id),
                "sequence": request.sequence,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

        return ChunkUploadResponse(
            session_id=request.session_id,
            sequence=request.sequence,
            stored_key=object_key,
            stream_message_id=message_id,
            status="stored",
        )

    def _stream_ttl(self) -> int:
        from src.core.config import get_settings

        return get_settings().CHUNK_IDEMPOTENCY_TTL_S


def _stream_fields(message: StreamMessage) -> dict[str, str]:
    return {
        "session_id": str(message.session_id),
        "subject_id": str(message.subject_id),
        "sequence": str(message.sequence),
        "timestamp_ms": str(message.timestamp_ms),
        "duration_ms": str(message.duration_ms),
        "object_key": message.object_key,
        "received_at": message.received_at.isoformat(),
    }


__all__ = [
    "ChunkIngestionService",
    "ChunkUploadRequest",
    "ChunkUploadResponse",
    "Session",
    "SessionNotAcceptingChunksError",
    "StreamMessage",
    "build_object_key",
    "idempotency_key",
]
