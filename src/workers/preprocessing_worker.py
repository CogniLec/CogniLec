"""Valkey Stream consumer that runs audio chunks through the pre-processing chain (S17)."""

from __future__ import annotations

import asyncio
import json
import logging
import socket
from uuid import UUID

from src.core.config import Settings, get_settings
from src.services.audio_chain.chain import AudioPreprocessingChain
from src.services.audio_chain.models import PreprocessingResult
from src.services.storage.client import StorageClient
from src.services.storage.models import BucketName
from src.services.valkey_stream import AUDIO_CHUNK_STREAM, ValkeyStreamProducer

logger = logging.getLogger(__name__)

CONSUMER_GROUP = "preprocessing"


def build_processed_object_key(session_id: UUID, sequence: int) -> str:
    """Return the MinIO object key for a processed chunk: {session_id}/processed/{seq:05d}.wav."""
    return f"{session_id}/processed/{sequence:05d}.wav"


def build_processed_stream_fields(
    session_id: UUID,
    sequence: int,
    object_key: str,
    result: PreprocessingResult,
    is_final: bool = False,
) -> dict[str, str]:
    """Build the `audio.processed` stream message fields (spec section 5).

    is_final must be carried through from the incoming audio.chunk message
    -- without it, asr_worker.py's fields.get("final", "false") always sees
    "false" and a session can never transition to TRANSCRIBED, since this
    function previously built its output fields from scratch and silently
    dropped whatever "final" value the chunk message actually had.
    """
    vad_regions = [
        {"start_ms": r.start_ms, "end_ms": r.end_ms, "confidence": r.confidence}
        for r in result.chunk.vad_regions
    ]
    return {
        "session_id": str(session_id),
        "sequence": str(sequence),
        "object_key": object_key,
        "has_speech": "true" if result.chunk.has_speech else "false",
        "speech_ratio": str(result.chunk.speech_ratio),
        "vad_regions": json.dumps(vad_regions),
        "processing_latency_ms": str(result.chunk.processing_latency_ms),
        "final": "true" if is_final else "false",
    }


class PreprocessingWorker:
    """Consumes `audio.chunk`, runs the pre-processing chain, emits `audio.processed`."""

    def __init__(
        self,
        settings: Settings | None = None,
        storage: StorageClient | None = None,
        stream: ValkeyStreamProducer | None = None,
        chain: AudioPreprocessingChain | None = None,
        consumer_name: str | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._storage = storage or StorageClient(self._settings)
        self._stream = stream or ValkeyStreamProducer(self._settings)
        self._chain = chain or AudioPreprocessingChain(
            vad_threshold=self._settings.VAD_THRESHOLD,
            vad_min_speech_ms=self._settings.VAD_MIN_SPEECH_MS,
            loudnorm_target_lufs=self._settings.LOUDNORM_TARGET_LUFS,
            loudnorm_tp=self._settings.LOUDNORM_TP,
            chain_timeout_s=self._settings.CHAIN_TIMEOUT_S,
            deepfilter_enabled=self._settings.DEEPFILTER_ENABLED,
        )
        self._consumer_name = consumer_name or f"preprocessing-worker-{socket.gethostname()}"

    async def start(self) -> None:
        """Ensure the consumer group exists, ready to poll with `run_once`/`run_forever`."""
        await self._stream.ensure_consumer_group(AUDIO_CHUNK_STREAM, CONSUMER_GROUP)

    async def process_message(self, message_id: str, fields: dict[str, str]) -> None:
        """Process one `audio.chunk` message end to end and acknowledge it."""
        session_id = UUID(fields["session_id"])
        sequence = int(fields["sequence"])
        object_key = fields["object_key"]
        is_final = fields.get("final", "false") == "true"

        if not self._settings.PREPROCESSING_ENABLED:
            logger.warning("PREPROCESSING_ENABLED=false; skipping chain (emergency bypass)")
            await self._stream.xack(AUDIO_CHUNK_STREAM, CONSUMER_GROUP, message_id)
            return

        try:
            input_bytes = await self._storage.get_object(BucketName.AUDIO, object_key)
            result = self._chain.process(input_bytes, session_id, sequence)

            processed_key = build_processed_object_key(session_id, sequence)
            await self._storage.put_object(
                BucketName.AUDIO,
                processed_key,
                result.chunk.audio_data,
                content_type="audio/wav",
            )

            out_fields = build_processed_stream_fields(
                session_id, sequence, processed_key, result, is_final=is_final
            )
            await self._stream.xadd_processed(out_fields)
            logger.info(
                "chunk processed",
                extra={
                    "session_id": str(session_id),
                    "sequence": sequence,
                    "has_speech": result.chunk.has_speech,
                    "latency_ms": result.chunk.processing_latency_ms,
                },
            )
        except Exception:
            logger.exception(
                "chunk processing failed",
                extra={"session_id": str(session_id), "sequence": sequence},
            )
        finally:
            await self._stream.xack(AUDIO_CHUNK_STREAM, CONSUMER_GROUP, message_id)

    async def run_once(self, count: int = 10, block_ms: int = 5000) -> int:
        """Poll once for up to `count` messages; process and ack each. Returns count handled."""
        messages = await self._stream.xreadgroup(
            AUDIO_CHUNK_STREAM, CONSUMER_GROUP, self._consumer_name, count=count, block_ms=block_ms
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
    worker = PreprocessingWorker()
    await worker.start()
    await worker.run_forever()


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(main())
