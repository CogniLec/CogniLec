"""Tests for src/api/routes/auth.py, including /auth/refresh.

No existing test file exercised these routes end to end (only manual
curl during earlier development) -- this covers register -> login ->
refresh -> me, and the failure paths /refresh should reject.
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from src.api.dependencies.auth import create_refresh_token
from src.api.dependencies.database import get_db_session
from src.api.routes.auth import router as auth_router

pytestmark = pytest.mark.integration


def _build_app(db_session: AsyncSession) -> FastAPI:
    app = FastAPI()
    app.include_router(auth_router, prefix="/api/v1")

    async def _override_db() -> AsyncSession:
        return db_session

    app.dependency_overrides[get_db_session] = _override_db
    return app


async def _register_and_login(client: httpx.AsyncClient, email: str) -> dict[str, str]:
    await client.post("/api/v1/auth/register", json={"email": email, "password": "password123"})
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    assert resp.status_code == 200
    tokens: dict[str, str] = resp.json()
    return tokens


class TestAuthRefresh:
    async def test_refresh_returns_a_new_working_token_pair(self, db_session: AsyncSession) -> None:
        app = _build_app(db_session)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            tokens = await _register_and_login(client, "refresh-user@example.com")

            resp = await client.post(
                "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
            )
            assert resp.status_code == 200
            new_tokens = resp.json()
            assert new_tokens["access_token"]
            assert new_tokens["refresh_token"]

            # the new access token actually works against a protected route
            me_resp = await client.get(
                "/api/v1/auth/me",
                headers={"Authorization": f"Bearer {new_tokens['access_token']}"},
            )
            assert me_resp.status_code == 200
            assert me_resp.json()["email"] == "refresh-user@example.com"

    async def test_refresh_rejects_an_access_token(self, db_session: AsyncSession) -> None:
        """An access token must not double as a refresh token."""
        app = _build_app(db_session)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            tokens = await _register_and_login(client, "swap-user@example.com")

            resp = await client.post(
                "/api/v1/auth/refresh", json={"refresh_token": tokens["access_token"]}
            )
        assert resp.status_code == 401

    async def test_refresh_rejects_garbage_token(self, db_session: AsyncSession) -> None:
        app = _build_app(db_session)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/auth/refresh", json={"refresh_token": "not-a-real-token"}
            )
        assert resp.status_code == 401

    async def test_refresh_rejects_a_deactivated_users_token(
        self, db_session: AsyncSession
    ) -> None:
        app = _build_app(db_session)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            tokens = await _register_and_login(client, "deactivated-user@example.com")

        await db_session.execute(
            text("UPDATE users SET is_active = false WHERE email = :email"),
            {"email": "deactivated-user@example.com"},
        )
        await db_session.commit()

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
            )
        assert resp.status_code == 401

    async def test_refresh_rejects_a_token_for_a_nonexistent_user(
        self, db_session: AsyncSession
    ) -> None:
        app = _build_app(db_session)
        transport = httpx.ASGITransport(app=app)
        bogus_refresh = create_refresh_token(data={"sub": str(uuid.uuid4())})
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": bogus_refresh})
        assert resp.status_code == 401
