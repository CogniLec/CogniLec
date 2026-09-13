"""Tests for S27 - Prefect process_session flow (T27.2, T27.4).

Prefect flows/tasks are called as plain async functions here (`.fn`/direct
await through the decorated callable works under Prefect's local test mode
without a running Prefect server) - there is no `fixture_prefect_server`
testcontainer in this environment, so T27.1/T27.5 (event-trigger latency,
worker-kill mid-task) are not exercised; the gate/idempotency logic they
depend on (NFR-R3 gate, cache-key idempotency) is verified directly instead.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.models.session import Session, SessionStatus
from src.db.models.subject import Subject
from src.db.models.user import User
from src.ml.embedding.client import EmbeddingClient
from src.ml.embedding.flows import FlowAbortError, _cache_key_t1, process_session

pytestmark = pytest.mark.integration


async def _subject_and_session(
    db: AsyncSession, status: SessionStatus
) -> tuple[uuid.UUID, uuid.UUID]:
    user = User(email=f"t-{uuid.uuid4().hex[:8]}@x.com", hashed_password="h", is_active=True)
    db.add(user)
    await db.flush()
    subject = Subject(user_id=user.id, name="S27 Subject")
    db.add(subject)
    await db.flush()
    session_obj = Session(subject_id=subject.id, session_type="content", status=status)
    db.add(session_obj)
    await db.flush()
    return subject.id, session_obj.id


class FakeClient(EmbeddingClient):
    def __init__(self) -> None:
        super().__init__(fallback_local=True)

    async def embed(self, texts, task_mode="retrieval"):  # type: ignore[override]
        return [[0.1] * 1024 for _ in texts]


class TestT272NfrR3Gate:
    async def test_flow_aborts_when_not_transcribed(self, db_session: AsyncSession) -> None:
        """T27.2: session in 'created' status -> flow refuses to start."""
        subject_id, session_id = await _subject_and_session(db_session, SessionStatus.CREATED)
        with pytest.raises(FlowAbortError):
            await process_session(
                session_id=session_id,
                subject_id=subject_id,
                embed_model_ver="qwen3-0.6b-v1",
                db=db_session,
                client=FakeClient(),
            )

    async def test_flow_proceeds_when_transcribed(self, db_session: AsyncSession) -> None:
        subject_id, session_id = await _subject_and_session(db_session, SessionStatus.TRANSCRIBED)
        result = await process_session(
            session_id=session_id,
            subject_id=subject_id,
            embed_model_ver="qwen3-0.6b-v1",
            db=db_session,
            client=FakeClient(),
        )
        assert result.success is True
        refreshed = await db_session.get(Session, session_id)
        assert refreshed is not None
        assert refreshed.status == SessionStatus.COMPLETE


class TestT274CacheKey:
    def test_cache_key_differs_by_version(self) -> None:
        """T27.4: changing embed_model_ver produces a different cache key -> cache miss."""
        session_id = uuid.uuid4()
        key_v1 = _cache_key_t1(None, {"session_id": session_id, "embed_model_ver": "v1"})
        key_v2 = _cache_key_t1(None, {"session_id": session_id, "embed_model_ver": "v2"})
        assert key_v1 != key_v2

    def test_cache_key_stable_for_same_params(self) -> None:
        """T27.3: re-running with the same (session_id, embed_model_ver) reuses the cache key."""
        session_id = uuid.uuid4()
        key_a = _cache_key_t1(None, {"session_id": session_id, "embed_model_ver": "v1"})
        key_b = _cache_key_t1(None, {"session_id": session_id, "embed_model_ver": "v1"})
        assert key_a == key_b
