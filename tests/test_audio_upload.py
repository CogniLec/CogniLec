"""Audio file upload API tests."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession
from src.api.dependencies.auth import get_current_user
from src.api.dependencies.database import get_db_session
from src.api.dependencies.settings import get_app_settings
from src.api.dependencies.valkey import get_valkey_stream
from src.api.routes.audio_upload import router as audio_upload_router
from src.api.routes.sessions import router as sessions_router
from src.core.config import Settings
from src.db.models.subject import Subject
from src.db.models.user import User
from src.db.repositories.session_repo import SessionRepository
from src.services.audio_file_ingestion import AudioFileIngestionResult
from src.services.valkey_stream import ValkeyStreamProducer

pytestmark = pytest.mark.integration


def _settings() -> Settings:
    return Settings(MINIO_ENDPOINT="localhost:9000", VALKEY_URL="redis://localhost:6379/0")


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
    db_session: AsyncSession,
    stream: ValkeyStreamProducer,
    user_id: uuid.UUID,
) -> FastAPI:
    app = FastAPI()
    app.include_router(audio_upload_router, prefix="/api/v1")
    app.include_router(sessions_router, prefix="/api/v1")

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


def _make_audio_bytes(duration_ms: int = 1000) -> bytes:
    """Create minimal fake audio bytes for testing."""
    return b"\x00" * (duration_ms * 16)


class TestAudioFileUploadValidation:
    """Test input validation for audio file upload endpoint."""

    async def test_rejects_unsupported_format(self, db_session: AsyncSession) -> None:
        user, subject = await _create_user_and_subject(db_session)
        repo = SessionRepository(db_session)
        session_obj = await repo.create(subject.id)
        await db_session.commit()

        stream_mock = MagicMock(spec=ValkeyStreamProducer)
        app = _build_app(db_session, stream_mock, user.id)
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            files = {"file": ("test.txt", b"not audio", "text/plain")}
            response = await client.post(
                f"/api/v1/sessions/{session_obj.id}/audio-file",
                files=files,
            )

        assert response.status_code == 400
        assert "Unsupported audio format" in response.json()["detail"]

    async def test_rejects_empty_file(self, db_session: AsyncSession) -> None:
        user, subject = await _create_user_and_subject(db_session)
        repo = SessionRepository(db_session)
        session_obj = await repo.create(subject.id)
        await db_session.commit()

        stream_mock = MagicMock(spec=ValkeyStreamProducer)
        app = _build_app(db_session, stream_mock, user.id)
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            files = {"file": ("empty.mp3", b"", "audio/mpeg")}
            response = await client.post(
                f"/api/v1/sessions/{session_obj.id}/audio-file",
                files=files,
            )

        assert response.status_code == 400
        assert "empty" in response.json()["detail"].lower()

    async def test_rejects_nonexistent_session(self, db_session: AsyncSession) -> None:
        user, subject = await _create_user_and_subject(db_session)
        await db_session.commit()

        fake_session_id = uuid.uuid4()
        audio_bytes = _make_audio_bytes(1000)

        stream_mock = MagicMock(spec=ValkeyStreamProducer)
        app = _build_app(db_session, stream_mock, user.id)
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            files = {"file": ("test.mp3", audio_bytes, "audio/mpeg")}
            response = await client.post(
                f"/api/v1/sessions/{fake_session_id}/audio-file",
                files=files,
            )

        assert response.status_code == 404

    async def test_rejects_oversized_file(self, db_session: AsyncSession) -> None:
        user, subject = await _create_user_and_subject(db_session)
        repo = SessionRepository(db_session)
        session_obj = await repo.create(subject.id)
        await db_session.commit()

        stream_mock = MagicMock(spec=ValkeyStreamProducer)
        app = _build_app(db_session, stream_mock, user.id)
        transport = httpx.ASGITransport(app=app)

        oversized = b"\x00" * (201 * 1024 * 1024)  # 201MB

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            files = {"file": ("big.mp3", oversized, "audio/mpeg")}
            response = await client.post(
                f"/api/v1/sessions/{session_obj.id}/audio-file",
                files=files,
            )

        assert response.status_code == 413


class TestAudioFileUploadSuccess:
    """Test successful audio file upload with mocked ingestion."""

    async def test_upload_mp3_file(self, db_session: AsyncSession) -> None:
        user, subject = await _create_user_and_subject(db_session)
        repo = SessionRepository(db_session)
        session_obj = await repo.create(subject.id)
        await db_session.commit()

        stream_mock = MagicMock(spec=ValkeyStreamProducer)
        app = _build_app(db_session, stream_mock, user.id)
        transport = httpx.ASGITransport(app=app)

        mock_result = AudioFileIngestionResult(
            session_id=session_obj.id,
            filename="test.mp3",
            total_chunks=1,
            duration_ms=5000,
        )

        with patch("src.api.routes.audio_upload.AudioFileIngestionService") as mock_cls:
            mock_service = AsyncMock()
            mock_cls.return_value = mock_service
            mock_service.ingest_audio_file.return_value = mock_result

            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                audio_bytes = _make_audio_bytes(5000)
                files = {"file": ("test.mp3", audio_bytes, "audio/mpeg")}
                response = await client.post(
                    f"/api/v1/sessions/{session_obj.id}/audio-file",
                    files=files,
                )

            assert response.status_code == 202
            body = response.json()
            assert body["status"] == "accepted"
            assert body["total_chunks"] == 1
            assert body["filename"] == "test.mp3"
            assert "5s" in body["message"]

    async def test_upload_wav_file(self, db_session: AsyncSession) -> None:
        user, subject = await _create_user_and_subject(db_session)
        repo = SessionRepository(db_session)
        session_obj = await repo.create(subject.id)
        await db_session.commit()

        stream_mock = MagicMock(spec=ValkeyStreamProducer)
        app = _build_app(db_session, stream_mock, user.id)
        transport = httpx.ASGITransport(app=app)

        mock_result = AudioFileIngestionResult(
            session_id=session_obj.id,
            filename="test.wav",
            total_chunks=2,
            duration_ms=45000,
        )

        with patch("src.api.routes.audio_upload.AudioFileIngestionService") as mock_cls:
            mock_service = AsyncMock()
            mock_cls.return_value = mock_service
            mock_service.ingest_audio_file.return_value = mock_result

            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                audio_bytes = _make_audio_bytes(45000)
                files = {"file": ("test.wav", audio_bytes, "audio/wav")}
                response = await client.post(
                    f"/api/v1/sessions/{session_obj.id}/audio-file",
                    files=files,
                )

            assert response.status_code == 202
            body = response.json()
            assert body["total_chunks"] == 2
            assert body["filename"] == "test.wav"
            assert "45s" in body["message"]
