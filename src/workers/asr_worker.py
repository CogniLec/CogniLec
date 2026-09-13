"""Valkey Stream consumer that transcribes preprocessed audio chunks (S19).

Consumes `audio.processed` (consumer group `asr`), downloads the processed
WAV via StorageClient, runs faster-whisper transcription, persists
utterances to DB-1, and transitions the session `recording -> transcribed`
atomically with the last utterance commit. Implements crash recovery: a
chunk whose sequence already has persisted utterances is skipped rather
than reprocessed.
"""

from __future__ import annotations

import logging
import socket
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import Settings, get_settings
from src.db.models.session import SessionStatus
from src.db.repositories.session_repo import SessionRepository
from src.db.repositories.utterance_repo import UtteranceRepository
from src.services.asr.service import FasterWhisperASRService
from src.services.audio_chain.vad import read_wav_as_array
from src.services.storage.client import StorageClient
from src.services.storage.models import BucketName
from src.services.valkey_stream import AUDIO_PROCESSED_STREAM, ValkeyStreamProducer

logger = logging.getLogger(__name__)

CONSUMER_GROUP = "asr"

# Utterance `seq` values are derived from the chunk-level stream `sequence`
# as `sequence * SEQUENCE_STRIDE + local_index`, so multiple utterances
# produced from one chunk never collide with another chunk's utterances,
# and a chunk's completion can be recovered by floor-dividing any of its
# utterances' `seq` by this stride.
SEQUENCE_STRIDE = 1000


class ASRWorker:
    """Consumes `audio.processed`, transcribes, persists, transitions session state."""

    def __init__(
        self,
        session_factory: Any,
        settings: Settings | None = None,
        storage: StorageClient | None = None,
        stream: ValkeyStreamProducer | None = None,
        asr_service: FasterWhisperASRService | None = None,
        consumer_name: str | None = None,
    ) -> None:
        """`session_factory` is a zero-arg callable returning a new AsyncSession
        (e.g. `async_sessionmaker(...)`), so each message gets its own DB
        session/transaction rather than sharing one across concurrent work.
        """
        self._settings = settings or get_settings()
        self._session_factory = session_factory
        self._storage = storage or StorageClient(self._settings)
        self._stream = stream or ValkeyStreamProducer(self._settings)
        self._asr_service = asr_service or FasterWhisperASRService(
            model_name=self._settings.ASR_MODEL_NAME,
            compute_type=self._settings.ASR_COMPUTE_TYPE,
            device=self._settings.ASR_DEVICE,
            beam_size=self._settings.ASR_BEAM_SIZE,
            language=self._settings.ASR_LANGUAGE,
            embed_model_ver=self._settings.EMBED_MODEL_VER,
            word_timestamps=self._settings.ASR_WORD_TIMESTAMPS,
            alignment_model=self._settings.ASR_ALIGNMENT_MODEL,
            device_index=self._settings.ASR_CUDA_DEVICE,
        )
        self._consumer_name = consumer_name or f"asr-worker-{socket.gethostname()}"

    async def start(self) -> None:
        """Ensure the consumer group exists, ready to poll with `run_once`/`run_forever`."""
        await self._stream.ensure_consumer_group(AUDIO_PROCESSED_STREAM, CONSUMER_GROUP)

    async def process_message(self, message_id: str, fields: dict[str, str]) -> None:
        """Process one `audio.processed` message end to end and acknowledge it."""
        session_id = uuid.UUID(fields["session_id"])
        sequence = int(fields["sequence"])
        object_key = fields["object_key"]
        has_speech = fields.get("has_speech", "true") == "true"
        is_final = fields.get("final", "false") == "true"

        try:
            async with self._session_factory() as db_session:
                subject_id = await self._resolve_subject_id(db_session, session_id)

                utterance_repo = UtteranceRepository(db_session)
                existing = await utterance_repo.existing_sequences(subject_id, session_id)
                existing_chunks = {seq // SEQUENCE_STRIDE for seq in existing}
                if sequence in existing_chunks:
                    logger.info(
                        "crash recovery: skipping already-transcribed chunk",
                        extra={"session_id": str(session_id), "sequence": sequence},
                    )
                else:
                    await self._transcribe_and_persist(
                        db_session,
                        utterance_repo,
                        session_id,
                        subject_id,
                        sequence,
                        object_key,
                        has_speech,
                    )

                if is_final:
                    await self._finalize_session(db_session, session_id)

                await db_session.commit()
        except Exception:
            logger.exception(
                "chunk transcription failed",
                extra={"session_id": str(session_id), "sequence": sequence},
            )
        finally:
            await self._stream.xack(AUDIO_PROCESSED_STREAM, CONSUMER_GROUP, message_id)

    async def _resolve_subject_id(
        self, db_session: AsyncSession, session_id: uuid.UUID
    ) -> uuid.UUID:
        session_repo = SessionRepository(db_session)
        session_obj = await session_repo.get_or_raise(session_id)
        return session_obj.subject_id

    async def _transcribe_and_persist(
        self,
        db_session: AsyncSession,
        utterance_repo: UtteranceRepository,
        session_id: uuid.UUID,
        subject_id: uuid.UUID,
        sequence: int,
        object_key: str,
        has_speech: bool,
    ) -> None:
        if not has_speech:
            # Empty audio / no speech: emit no utterances for this chunk, but
            # it still counts as processed (edge case: still transition to
            # transcribed on the final chunk).
            logger.info(
                "chunk has no speech; no utterances emitted",
                extra={"session_id": str(session_id), "sequence": sequence},
            )
            return

        wav_bytes = await self._storage.get_object(BucketName.AUDIO, object_key)
        audio, sample_rate = read_wav_as_array(wav_bytes)

        # Utterance sequence numbers within a session are derived from the
        # chunk sequence * a large stride so multiple utterances per chunk
        # never collide with another chunk's utterances.
        sequence_start = sequence * SEQUENCE_STRIDE

        result = self._asr_service.transcribe_chunk(
            audio, sample_rate, session_id, subject_id, sequence_start
        )

        rows: list[dict[str, object]] = [
            {
                "session_id": u.session_id,
                "seq": u.sequence,
                "start_ms": u.start_ms,
                "end_ms": u.end_ms,
                "text": u.text,
                "asr_confidence": u.confidence,
                "words": [w.model_dump() for w in u.words],
                "speaker_tag": u.speaker_tag,
                "embed_model_ver": u.embed_model_ver,
            }
            for u in result.utterances
        ]
        await utterance_repo.bulk_insert(subject_id, rows)
        logger.info(
            "chunk transcribed",
            extra={
                "session_id": str(session_id),
                "sequence": sequence,
                "utterances": len(rows),
                "rtf": result.real_time_factor,
            },
        )

    async def _finalize_session(self, db_session: AsyncSession, session_id: uuid.UUID) -> None:
        """Transition the session recording -> transcribed atomically with the
        commit of the last utterance batch (NFR-R3: caller must commit()
        after this returns for the transition to become durable)."""
        session_repo = SessionRepository(db_session)
        session_obj = await session_repo.get_or_raise(session_id)
        await session_repo.update_status(session_obj, SessionStatus.TRANSCRIBED)

    async def run_once(self, count: int = 5, block_ms: int = 10000) -> int:
        """Poll once for up to `count` messages; process and ack each. Returns count handled."""
        messages = await self._stream.xreadgroup(
            AUDIO_PROCESSED_STREAM,
            CONSUMER_GROUP,
            self._consumer_name,
            count=count,
            block_ms=block_ms,
        )
        for message_id, fields in messages:
            await self.process_message(message_id, fields)
        return len(messages)

    async def run_forever(self) -> None:  # pragma: no cover - long-running loop
        """Poll indefinitely until cancelled."""
        await self.start()
        while True:
            await self.run_once()


async def main() -> None:  # pragma: no cover - process entrypoint
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    worker = ASRWorker(session_factory, settings=settings)
    await worker.start()
    await worker.run_forever()


if __name__ == "__main__":  # pragma: no cover
    import asyncio

    asyncio.run(main())
