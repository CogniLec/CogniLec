"""RetryQueue - Valkey-backed retry queue for failed sessions (S23).

Uses a Valkey sorted set (`lis:retry_queue`), score = eligible_at unix
timestamp, so a worker can poll `ZRANGEBYSCORE key -inf now` for jobs whose
backoff delay has elapsed. Retry metadata (reason, retry_count, enqueued_at)
is stored alongside as a JSON hash keyed by session_id.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from redis.asyncio import Redis

from src.core.config import Settings, get_settings

QUEUE_KEY = "lis:retry_queue"
META_KEY_PREFIX = "lis:retry_queue:meta:"


@dataclass
class RetryJob:
    session_id: UUID
    reason: str
    retry_count: int
    enqueued_at: datetime
    eligible_at: datetime


class RetryQueue:
    """Valkey/Redis-based retry queue for failed sessions."""

    MAX_RETRIES = 3
    RETRY_DELAY_SECONDS = 60

    def __init__(self, settings: Settings | None = None, client: Redis | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = client or Redis.from_url(self._settings.VALKEY_URL, decode_responses=True)

    def _meta_key(self, session_id: UUID) -> str:
        return f"{META_KEY_PREFIX}{session_id}"

    def _delay_for(self, retry_count: int) -> float:
        return float(self.RETRY_DELAY_SECONDS * (2**retry_count))

    async def enqueue(self, session_id: UUID, reason: str, retry_count: int = 0) -> None:
        """Add a failed session to the retry queue with exponential backoff."""
        now = time.time()
        eligible_at = now + self._delay_for(retry_count)
        meta = {
            "session_id": str(session_id),
            "reason": reason,
            "retry_count": retry_count,
            "enqueued_at": now,
            "eligible_at": eligible_at,
        }
        await self._client.set(self._meta_key(session_id), json.dumps(meta))
        await self._client.zadd(QUEUE_KEY, {str(session_id): eligible_at})

    async def dequeue(self) -> RetryJob | None:
        """Pop the next session eligible for retry (delay expired), if any."""
        now = time.time()
        candidates = await self._client.zrangebyscore(QUEUE_KEY, "-inf", now, start=0, num=1)
        if not candidates:
            return None
        session_id_str = candidates[0]
        removed = await self._client.zrem(QUEUE_KEY, session_id_str)
        if not removed:
            return None
        raw_meta = await self._client.get(self._meta_key(session_id_str))
        await self._client.delete(self._meta_key(session_id_str))
        if raw_meta is None:
            return None
        meta = json.loads(raw_meta)
        return RetryJob(
            session_id=UUID(meta["session_id"]),
            reason=meta["reason"],
            retry_count=meta["retry_count"],
            enqueued_at=datetime.fromtimestamp(meta["enqueued_at"], tz=UTC),
            eligible_at=datetime.fromtimestamp(meta["eligible_at"], tz=UTC),
        )

    async def mark_success(self, session_id: UUID) -> None:
        """Remove a session from the queue on successful reprocessing."""
        await self._client.zrem(QUEUE_KEY, str(session_id))
        await self._client.delete(self._meta_key(session_id))

    async def mark_permanent_failure(self, session_id: UUID, reason: str) -> None:
        """After MAX_RETRIES, remove the session from the retry queue permanently."""
        await self._client.zrem(QUEUE_KEY, str(session_id))
        await self._client.delete(self._meta_key(session_id))

    async def close(self) -> None:
        await self._client.aclose()
