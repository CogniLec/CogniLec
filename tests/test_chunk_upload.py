"""S16 - Chunk Upload API & Stream Ingestion tests (T16.1-T16.6)."""

from __future__ import annotations

import asyncio
import uuid

import httpx
import pytest
import uvicorn
from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from src.api.dependencies.auth import get_current_user
from src.api.dependencies.database import get_db_session
from src.api.dependencies.settings import get_app_settings
from src.api.dependencies.valkey import get_valkey_stream
from src.api.routes.chunks import router as chunks_router
from src.api.routes.session_stream import router as stream_router
from src.core.config import Settings
from src.db.models.session import SessionStatus
from src.db.models.subject import Subject
from src.db.models.user import User
from src.db.repositories.session_repo import SessionRepository
from src.services.storage.client import StorageClient
from src.services.storage.models import BucketName
from src.services.valkey_stream import ValkeyStreamProducer

pytestmark = pytest.mark.integration

DATABASE_URL = "postgresql+asyncpg://lis:lis_dev@localhost:5434/lis_test"
VALKEY_URL = "redis://localhost:6379/0"


def _settings() -> Settings:
    return Settings(MINIO_ENDPOINT="localhost:9000", VALKEY_URL=VALKEY_URL)


async def _create_user_and_subject(session: AsyncSession) -> tuple[User, Subject]:
    user = User(
        email=f"test-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="hashed",
        is_active=True,
    )
    session.add(user)
    await session.flush()

    subject = Subject(user_id=user.id, name="Test Subject")
    session.add(subject)
    await session.flush()
    return user, subject


def _build_app(
    db_session: AsyncSession, stream: ValkeyStreamProducer, user_id: uuid.UUID
) -> FastAPI:
    app = FastAPI()
    app.include_router(chunks_router, prefix="/api/v1")
    app.include_router(stream_router, prefix="/api/v1")

    async def _override_db() -> AsyncSession:
        return db_session

    async def _override_stream() -> ValkeyStreamProducer:
        return stream

    def _override_settings() -> Settings:
        return _settings()

    async def _override_user() -> dict[str, object]:
        return {"id": str(user_id), "email": "test@example.com"}

    app.dependency_overrides[get_db_session] = _override_db
    app.dependency_overrides[get_valkey_stream] = _override_stream
    app.dependency_overrides[get_app_settings] = _override_settings
    app.dependency_overrides[get_current_user] = _override_user
    return app


async def _client_for(
    db_session: AsyncSession, stream: ValkeyStreamProducer, user_id: uuid.UUID
) -> httpx.AsyncClient:
    app = _build_app(db_session, stream, user_id)
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture
async def valkey() -> Redis:
    client = Redis.from_url(VALKEY_URL, decode_responses=True)
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()


@pytest.fixture
async def stream(valkey: Redis) -> ValkeyStreamProducer:
    return ValkeyStreamProducer(settings=_settings(), client=valkey)


async def _upload_chunk(
    client: httpx.AsyncClient,
    session_id: uuid.UUID,
    sequence: int,
    *,
    timestamp_ms: int = 0,
    duration_ms: int = 1000,
    data: bytes = b"opus-bytes",
) -> httpx.Response:
    files = {"chunk": ("chunk.opus", data, "audio/opus")}
    form = {
        "sequence": str(sequence),
        "timestamp_ms": str(timestamp_ms),
        "duration_ms": str(duration_ms),
    }
    return await client.post(f"/api/v1/sessions/{session_id}/chunks", data=form, files=files)


class TestChunkStoredAndStreamed:
    """T16.1 - chunk uploaded, stored in MinIO, message present on stream."""

    async def test_chunk_stored_and_streamed(
        self, db_session: AsyncSession, stream: ValkeyStreamProducer, valkey: Redis
    ) -> None:
        user, subject = await _create_user_and_subject(db_session)
        repo = SessionRepository(db_session)
        session_obj = await repo.create(subject.id)
        await db_session.commit()

        async with await _client_for(db_session, stream, user.id) as client:
            response = await _upload_chunk(client, session_obj.id, 0)

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "stored"
        assert body["stored_key"] == f"{session_obj.id}/chunks/00000.opus"
        assert body["stream_message_id"] != ""

        storage = StorageClient(_settings())
        fetched = await storage.get_object(BucketName.AUDIO, body["stored_key"])
        assert fetched == b"opus-bytes"

        entries = await valkey.xrange("audio.chunk")
        assert any(
            fields.get("session_id") == str(session_obj.id) and fields.get("sequence") == "0"
            for _, fields in entries
        )

        refreshed = await repo.get(session_obj.id)
        assert refreshed is not None
        assert refreshed.status == SessionStatus.RECORDING

        await storage.delete_object(BucketName.AUDIO, body["stored_key"])


class TestDuplicateChunkIdempotent:
    """T16.2 - duplicate chunk accepted, not double-published."""

    async def test_duplicate_chunk_idempotent(
        self, db_session: AsyncSession, stream: ValkeyStreamProducer, valkey: Redis
    ) -> None:
        user, subject = await _create_user_and_subject(db_session)
        repo = SessionRepository(db_session)
        session_obj = await repo.create(subject.id)
        await db_session.commit()

        async with await _client_for(db_session, stream, user.id) as client:
            first = await _upload_chunk(client, session_obj.id, 0)
            second = await _upload_chunk(client, session_obj.id, 0)

        assert first.json()["status"] == "stored"
        assert second.json()["status"] == "duplicate"
        assert second.json()["stream_message_id"] == ""

        entries = await valkey.xrange("audio.chunk")
        matching = [
            fields
            for _, fields in entries
            if fields.get("session_id") == str(session_obj.id) and fields.get("sequence") == "0"
        ]
        assert len(matching) == 1

        storage = StorageClient(_settings())
        await storage.delete_object(BucketName.AUDIO, f"{session_obj.id}/chunks/00000.opus")


class TestCreatedToRecordingSurvivesLostFirstAttempt:
    """Regression: a real session got permanently stuck at CREATED despite
    hundreds of chunks actively streaming in and being fully transcribed
    (382 utterances). Root cause: the dedup key in Valkey and the Postgres
    status transition were not atomic with each other -- if chunk 0's
    first attempt marked the dedup key "stored" but failed before the DB
    commit landed, every retry of chunk 0 saw "already stored" and
    short-circuited before ever reaching the transition, permanently. This
    simulates exactly that: mark the dedup key as already stored (as if a
    first attempt got that far and no further, e.g. it crashed before the
    status transition committed) *before* ever calling the upload endpoint
    for chunk 0, then upload chunk 0 for real and confirm the session
    still reaches RECORDING even though the chunk itself was treated as a
    duplicate."""

    async def test_status_transition_survives_a_pre_existing_dedup_key(
        self, db_session: AsyncSession, stream: ValkeyStreamProducer, valkey: Redis
    ) -> None:
        user, subject = await _create_user_and_subject(db_session)
        repo = SessionRepository(db_session)
        session_obj = await repo.create(subject.id)
        await db_session.commit()

        # Simulate the lost-first-attempt: the dedup key already exists,
        # as if an earlier request got as far as marking it before failing.
        await valkey.set(f"chunk:{session_obj.id}:0", "stored")

        async with await _client_for(db_session, stream, user.id) as client:
            response = await _upload_chunk(client, session_obj.id, 0)

        assert response.json()["status"] == "duplicate"

        refreshed = await repo.get(session_obj.id)
        assert refreshed is not None
        assert refreshed.status == SessionStatus.RECORDING


class TestOutOfOrderChunks:
    """T16.3 - out-of-order chunks stored correctly by sequence."""

    async def test_out_of_order_chunks(
        self, db_session: AsyncSession, stream: ValkeyStreamProducer, valkey: Redis
    ) -> None:
        user, subject = await _create_user_and_subject(db_session)
        repo = SessionRepository(db_session)
        session_obj = await repo.create(subject.id)
        await repo.update_status(session_obj, SessionStatus.RECORDING)
        await db_session.commit()

        storage = StorageClient(_settings())
        stored_keys = []
        async with await _client_for(db_session, stream, user.id) as client:
            for seq in (2, 0, 1):
                response = await _upload_chunk(
                    client, session_obj.id, seq, data=f"seq-{seq}".encode()
                )
                assert response.json()["status"] == "stored"
                stored_keys.append(response.json()["stored_key"])

        for seq in (2, 0, 1):
            key = f"{session_obj.id}/chunks/{seq:05d}.opus"
            fetched = await storage.get_object(BucketName.AUDIO, key)
            assert fetched == f"seq-{seq}".encode()

        entries = await valkey.xrange("audio.chunk")
        matching_seqs = {
            fields["sequence"]
            for _, fields in entries
            if fields.get("session_id") == str(session_obj.id)
        }
        assert matching_seqs == {"0", "1", "2"}

        for key in stored_keys:
            await storage.delete_object(BucketName.AUDIO, key)


class TestConcurrentSessions:
    """T16.4 - 20 concurrent sessions sustained without backlog growth (NFR-P7)."""

    async def test_concurrent_sessions(
        self, db_session: AsyncSession, test_user_id: uuid.UUID
    ) -> None:
        # db_session's fixture drops/recreates the schema per test; independent
        # DB connections/sessions are used per concurrent task below (matching
        # how real concurrent HTTP requests would each get their own connection)
        # rather than sharing db_session's single AsyncSession across tasks.
        await db_session.commit()

        subject = Subject(user_id=test_user_id, name="ConcurrentSubject")
        db_session.add(subject)
        await db_session.flush()
        await db_session.commit()
        subject_id = subject.id

        engine = create_async_engine(DATABASE_URL)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        settings = _settings()
        valkey_client = Redis.from_url(VALKEY_URL, decode_responses=True)
        await valkey_client.flushdb()
        stream = ValkeyStreamProducer(settings=settings, client=valkey_client)
        storage = StorageClient(settings)

        async def run_session(session_index: int) -> uuid.UUID:
            async with session_factory() as session:
                repo = SessionRepository(session)
                session_obj = await repo.create(subject_id)
                await session.commit()
                app = _build_app(session, stream, test_user_id)
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                    for seq in range(10):
                        response = await _upload_chunk(
                            client,
                            session_obj.id,
                            seq,
                            data=f"s{session_index}-c{seq}".encode(),
                        )
                        assert response.status_code == 200
                return session_obj.id

        try:
            session_ids = await asyncio.gather(*(run_session(i) for i in range(20)))
        finally:
            await engine.dispose()
            await valkey_client.aclose()

        assert len(session_ids) == 20

        verify_client = Redis.from_url(VALKEY_URL, decode_responses=True)
        total = await verify_client.xlen("audio.chunk")
        assert total == 200, f"expected 200 stream messages, got {total}"
        await verify_client.aclose()

        for sid in session_ids:
            for seq in range(10):
                key = f"{sid}/chunks/{seq:05d}.opus"
                await storage.delete_object(BucketName.AUDIO, key)


class TestSSEStatusEvents:
    """T16.5 - SSE stream emits status transitions in order."""

    async def test_sse_status_events(
        self, db_session: AsyncSession, stream: ValkeyStreamProducer, valkey: Redis
    ) -> None:
        # httpx's ASGITransport buffers the whole ASGI app call and only
        # returns once the body is fully sent (more_body: False) - it does
        # not support genuinely streaming, never-ending responses like SSE.
        # So this test runs the app on a real uvicorn server over a real
        # socket, which streams chunks as they're produced.
        user, subject = await _create_user_and_subject(db_session)
        repo = SessionRepository(db_session)
        session_obj = await repo.create(subject.id)
        await db_session.commit()

        app = _build_app(db_session, stream, user.id)
        port = 18916
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        server = uvicorn.Server(config)
        server_task = asyncio.create_task(server.serve())
        try:
            for _ in range(200):
                if server.started:
                    break
                await asyncio.sleep(0.02)
            assert server.started, "uvicorn server did not start in time"

            base_url = f"http://127.0.0.1:{port}"

            async def upload_after_delay() -> None:
                await asyncio.sleep(0.3)
                async with httpx.AsyncClient(base_url=base_url) as client:
                    await _upload_chunk(client, session_obj.id, 0)

            events: list[tuple[str, str]] = []

            async def read_stream() -> None:
                async with (
                    httpx.AsyncClient(base_url=base_url) as client,
                    client.stream("GET", f"/api/v1/sessions/{session_obj.id}/stream") as response,
                ):
                    current_event = ""
                    async for line in response.aiter_lines():
                        if line.startswith("event:"):
                            current_event = line.split(":", 1)[1].strip()
                        elif line.startswith("data:"):
                            events.append((current_event, line.split(":", 1)[1].strip()))
                            if current_event == "status_changed":
                                return

            upload_task = asyncio.create_task(upload_after_delay())
            try:
                await asyncio.wait_for(read_stream(), timeout=15)
            finally:
                await upload_task
        finally:
            server.should_exit = True
            await server_task

        status_events = [e for e in events if e[0] == "status_changed"]
        assert len(status_events) >= 1
        assert "recording" in status_events[0][1]

        storage = StorageClient(_settings())
        await storage.delete_object(BucketName.AUDIO, f"{session_obj.id}/chunks/00000.opus")


class TestChunkRejectedAfterComplete:
    """T16.6 - chunk for a complete session is rejected."""

    async def test_chunk_rejected_after_complete(
        self, db_session: AsyncSession, stream: ValkeyStreamProducer
    ) -> None:
        user, subject = await _create_user_and_subject(db_session)
        repo = SessionRepository(db_session)
        session_obj = await repo.create(subject.id)
        await repo.update_status(session_obj, SessionStatus.RECORDING)
        await repo.update_status(session_obj, SessionStatus.TRANSCRIBED)
        await repo.update_status(session_obj, SessionStatus.PROCESSING)
        await repo.update_status(session_obj, SessionStatus.COMPLETE)
        await db_session.commit()

        async with await _client_for(db_session, stream, user.id) as client:
            response = await _upload_chunk(client, session_obj.id, 0)

        assert response.status_code == 409
        assert "complete" in response.json()["detail"].lower()
