"""Valkey Stream producer + pub/sub helper for chunk ingestion (S16)."""

from __future__ import annotations

import json
from typing import Any

from redis.asyncio import Redis
from redis.asyncio.client import PubSub
from src.core.config import Settings, get_settings

AUDIO_CHUNK_STREAM = "audio.chunk"
AUDIO_PROCESSED_STREAM = "audio.processed"
AUDIO_QUALITY_STREAM = "audio.quality"


def _status_channel(session_id: str) -> str:
    """Return the pub/sub channel name used for a session's status/chunk events."""
    return f"session:{session_id}:events"


class ValkeyStreamProducer:
    """Thin async wrapper around a redis-py client pointed at Valkey."""

    def __init__(self, settings: Settings | None = None, client: Redis | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = client or Redis.from_url(self._settings.VALKEY_URL, decode_responses=True)

    @property
    def client(self) -> Redis:
        return self._client

    async def close(self) -> None:
        await self._client.aclose()

    async def set_if_not_exists(self, key: str, value: str, ttl_s: int) -> bool:
        """SET key value NX EX ttl_s. Returns True if the key was newly set."""
        result = await self._client.set(key, value, nx=True, ex=ttl_s)
        return bool(result)

    async def xadd_chunk(self, fields: dict[str, str]) -> str:
        """XADD to the audio.chunk stream and return the message id."""
        message_id = await self._client.xadd(AUDIO_CHUNK_STREAM, fields)  # type: ignore[arg-type]
        return str(message_id)

    async def publish_event(self, session_id: str, event: str, data: dict[str, Any]) -> None:
        """Publish an SSE-forwardable event on the session's pub/sub channel."""
        payload = json.dumps({"event": event, "data": data})
        await self._client.publish(_status_channel(session_id), payload)

    async def subscribe(self, session_id: str) -> PubSub:
        """Return a pub/sub object subscribed to the session's event channel."""
        pubsub = self._client.pubsub()
        await pubsub.subscribe(_status_channel(session_id))
        return pubsub

    async def xadd_processed(self, fields: dict[str, str]) -> str:
        """XADD to the audio.processed stream and return the message id."""
        message_id = await self._client.xadd(AUDIO_PROCESSED_STREAM, fields)  # type: ignore[arg-type]
        return str(message_id)

    async def xadd_quality(self, fields: dict[str, str]) -> str:
        """XADD to the audio.quality stream and return the message id."""
        message_id = await self._client.xadd(AUDIO_QUALITY_STREAM, fields)  # type: ignore[arg-type]
        return str(message_id)

    async def ensure_consumer_group(self, stream: str, group: str) -> None:
        """Create a consumer group starting at '$' if it doesn't already exist."""
        try:
            await self._client.xgroup_create(stream, group, id="$", mkstream=True)
        except Exception as exc:  # BUSYGROUP: group already exists
            if "BUSYGROUP" not in str(exc):
                raise

    async def xreadgroup(
        self,
        stream: str,
        group: str,
        consumer: str,
        count: int = 10,
        block_ms: int = 5000,
    ) -> list[tuple[str, dict[str, str]]]:
        """XREADGROUP for one stream; returns a flat list of (message_id, fields)."""
        response = await self._client.xreadgroup(
            groupname=group,
            consumername=consumer,
            streams={stream: ">"},
            count=count,
            block=block_ms,
        )
        if not response:
            return []
        results: list[tuple[str, dict[str, str]]] = []
        for _stream_name, messages in response:
            for message_id, fields in messages:
                results.append((str(message_id), dict(fields)))
        return results

    async def xack(self, stream: str, group: str, message_id: str) -> None:
        """Acknowledge a processed message."""
        await self._client.xack(stream, group, message_id)
