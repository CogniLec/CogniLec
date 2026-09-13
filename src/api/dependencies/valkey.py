"""Valkey client dependency for FastAPI (S16)."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from src.services.valkey_stream import ValkeyStreamProducer

_producer: ValkeyStreamProducer | None = None


def _get_producer() -> ValkeyStreamProducer:
    global _producer
    if _producer is None:
        _producer = ValkeyStreamProducer()
    return _producer


async def get_valkey_stream() -> AsyncGenerator[ValkeyStreamProducer, None]:
    """Yield a shared Valkey stream producer/pub-sub helper."""
    yield _get_producer()
