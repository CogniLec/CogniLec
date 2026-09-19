"""Audio file ingestion service — splits uploaded audio into chunks and feeds the pipeline."""

from __future__ import annotations

import logging
import math
import subprocess
from dataclasses import dataclass
from uuid import UUID

from src.services.audio_chain.resample import resolve_ffmpeg_binary
from src.services.chunk_ingestion import (
    ChunkIngestionService,
    ChunkUploadRequest,
    SessionNotAcceptingChunksError,
)
from src.services.storage.client import StorageClient

logger = logging.getLogger(__name__)

CHUNK_DURATION_MS = 30_000  # 30 seconds, matches Recorder.ts default
ALLOWED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".webm", ".aac", ".wma"}
ALLOWED_MIME_TYPES = {
    "audio/mpeg",  # mp3
    "audio/wav",  # wav
    "audio/x-wav",  # wav alt
    "audio/wave",  # wav alt
    "audio/x-m4a",  # m4a
    "audio/mp4",  # m4a/aac
    "audio/flac",  # flac
    "audio/ogg",  # ogg
    "audio/webm",  # webm
    "audio/aac",  # aac
    "audio/x-ms-wma",  # wma
    "audio/*",  # wildcard fallback
}


@dataclass
class AudioFileIngestionResult:
    session_id: UUID
    filename: str
    total_chunks: int
    duration_ms: int


def _probe_duration_ms(audio_bytes: bytes) -> int:
    """Probe audio duration in milliseconds using ffprobe."""
    binary = resolve_ffmpeg_binary()
    ffprobe_binary = binary.replace("ffmpeg", "ffprobe")
    if ffprobe_binary == binary:
        # ffprobe not found alongside ffmpeg, try system path
        import shutil

        ffprobe_binary = shutil.which("ffprobe") or binary

    result = subprocess.run(
        [
            ffprobe_binary,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            "pipe:0",
        ],
        input=audio_bytes,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace")[:500]
        msg = f"ffprobe failed: {stderr}"
        raise AudioFileIngestionError(msg)

    duration_str = result.stdout.decode(errors="replace").strip()
    if not duration_str:
        msg = "ffprobe returned empty duration"
        raise AudioFileIngestionError(msg)
    return int(float(duration_str) * 1000)


def _split_audio_chunk(audio_bytes: bytes, start_ms: int, duration_ms: int) -> bytes:
    """Extract a chunk from audio bytes using ffmpeg."""
    binary = resolve_ffmpeg_binary()
    start_s = start_ms / 1000.0
    result = subprocess.run(
        [
            binary,
            "-i",
            "pipe:0",
            "-ss",
            str(start_s),
            "-t",
            str(duration_ms / 1000.0),
            "-f",
            "opus",
            "-c:a",
            "libopus",
            "-b:a",
            "32k",
            "pipe:1",
        ],
        input=audio_bytes,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace")[:500]
        msg = f"ffmpeg chunk extraction failed: {stderr}"
        raise AudioFileIngestionError(msg)
    if not result.stdout:
        msg = "ffmpeg produced empty output for chunk"
        raise AudioFileIngestionError(msg)
    return result.stdout


class AudioFileIngestionError(Exception):
    """Raised when audio file ingestion fails."""


class AudioFileIngestionService:
    """Splits an uploaded audio file into chunks and feeds them into the pipeline."""

    def __init__(
        self,
        chunk_ingestion: ChunkIngestionService,
        storage: StorageClient,
    ) -> None:
        self._chunk_ingestion = chunk_ingestion
        self._storage = storage

    async def ingest_audio_file(
        self,
        session_id: UUID,
        filename: str,
        audio_bytes: bytes,
    ) -> AudioFileIngestionResult:
        """Split audio file into 30s chunks and ingest each into the pipeline."""
        duration_ms = _probe_duration_ms(audio_bytes)
        if duration_ms <= 0:
            msg = "Audio file has no detectable audio content"
            raise AudioFileIngestionError(msg)

        total_chunks = max(1, math.ceil(duration_ms / CHUNK_DURATION_MS))
        logger.info(
            "audio_file_ingestion_started",
            extra={
                "session_id": str(session_id),
                "filename": filename,
                "duration_ms": duration_ms,
                "total_chunks": total_chunks,
            },
        )

        for seq in range(total_chunks):
            start_ms = seq * CHUNK_DURATION_MS
            chunk_duration = min(CHUNK_DURATION_MS, duration_ms - start_ms)
            is_final = seq == total_chunks - 1

            chunk_bytes = _split_audio_chunk(audio_bytes, start_ms, chunk_duration)

            request = ChunkUploadRequest(
                session_id=session_id,
                sequence=seq,
                timestamp_ms=start_ms,
                duration_ms=chunk_duration,
                is_final=is_final,
            )

            try:
                await self._chunk_ingestion.ingest_chunk(request, chunk_bytes)
            except SessionNotAcceptingChunksError:
                logger.warning(
                    "audio_file_session_not_accepting",
                    extra={"session_id": str(session_id), "sequence": seq},
                )
                break

            logger.info(
                "audio_file_chunk_ingested",
                extra={
                    "session_id": str(session_id),
                    "sequence": seq,
                    "start_ms": start_ms,
                    "duration_ms": chunk_duration,
                    "is_final": is_final,
                },
            )

        logger.info(
            "audio_file_ingestion_complete",
            extra={
                "session_id": str(session_id),
                "total_chunks": total_chunks,
                "duration_ms": duration_ms,
            },
        )
        return AudioFileIngestionResult(
            session_id=session_id,
            filename=filename,
            total_chunks=total_chunks,
            duration_ms=duration_ms,
        )
