"""FastAPI router - SSE session status stream (S16)."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from src.api.dependencies.database import get_db_session
from src.api.dependencies.settings import get_app_settings
from src.api.dependencies.valkey import get_valkey_stream
from src.core.config import Settings
from src.db.exceptions import SessionNotFoundError
from src.db.repositories.session_repo import SessionRepository
from src.services.valkey_stream import ValkeyStreamProducer

router = APIRouter(prefix="/sessions", tags=["stream"])


async def _event_generator(
    session_id: uuid.UUID,
    stream: ValkeyStreamProducer,
    settings: Settings,
) -> AsyncIterator[dict[str, str]]:
    # Disconnect detection is handled by EventSourceResponse itself (it races
    # this generator against its own request.is_disconnected() poller and
    # cancels/cleans up on client disconnect), so we don't poll for it here -
    # doing so would block on ASGI transports that only deliver a disconnect
    # message when the connection actually closes.
    pubsub = await stream.subscribe(str(session_id))
    try:
        while True:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True,
                timeout=settings.SSE_HEARTBEAT_INTERVAL_S,
            )
            if message is None:
                yield {
                    "event": "heartbeat",
                    "data": json.dumps({"timestamp": datetime.now(UTC).isoformat()}),
                }
                continue
            payload: dict[str, Any] = json.loads(message["data"])
            yield {"event": payload["event"], "data": json.dumps(payload["data"])}
    finally:
        await pubsub.unsubscribe()
        await pubsub.aclose()


@router.get("/{session_id}/stream")
async def stream_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
    stream: ValkeyStreamProducer = Depends(get_valkey_stream),
    settings: Settings = Depends(get_app_settings),
) -> EventSourceResponse:
    repo = SessionRepository(db)
    try:
        await repo.get_or_raise(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return EventSourceResponse(_event_generator(session_id, stream, settings))
