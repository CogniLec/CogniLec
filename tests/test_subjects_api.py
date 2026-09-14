"""Route-level regression test for src/api/routes/subjects.py.

Found by actually running the app end to end (not through a test fixture):
create_subject/list_subjects used `user_id = uuid.uuid4()` -- a fresh
random UUID on every call, never the real authenticated user (a leftover
`# TODO: extract user_id from auth token`). tests/test_subjects.py only
ever exercised SubjectRepository directly, never this route, so the bug
was invisible to the existing suite. This test goes through the actual
route with a real auth override, the way a live client does.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession
from src.api.dependencies.auth import get_current_user
from src.api.dependencies.database import get_db_session
from src.api.routes.subjects import router as subjects_router
from src.db.models.user import User

pytestmark = pytest.mark.integration


def _build_app(db_session: AsyncSession, current_user: dict[str, Any]) -> FastAPI:
    app = FastAPI()
    app.include_router(subjects_router, prefix="/api/v1")

    async def _override_db() -> AsyncSession:
        return db_session

    async def _override_user() -> dict[str, Any]:
        return current_user

    app.dependency_overrides[get_db_session] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    return app


@pytest.mark.asyncio
async def test_created_subject_is_owned_by_the_authenticated_user(
    db_session: AsyncSession,
) -> None:
    user = User(email=f"t-{uuid.uuid4().hex[:8]}@example.com", hashed_password="h", is_active=True)
    db_session.add(user)
    await db_session.flush()

    app = _build_app(db_session, {"id": str(user.id), "email": user.email})
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        create_resp = await client.post("/api/v1/subjects/", json={"name": "Route Test Subject"})
        assert create_resp.status_code == 201
        assert create_resp.json()["user_id"] == str(user.id)

        list_resp = await client.get("/api/v1/subjects/")
        assert list_resp.status_code == 200
        body = list_resp.json()
        assert body["total"] == 1
        assert body["items"][0]["user_id"] == str(user.id)


@pytest.mark.asyncio
async def test_two_users_each_only_see_their_own_subjects(db_session: AsyncSession) -> None:
    user_a = User(
        email=f"a-{uuid.uuid4().hex[:8]}@example.com", hashed_password="h", is_active=True
    )
    user_b = User(
        email=f"b-{uuid.uuid4().hex[:8]}@example.com", hashed_password="h", is_active=True
    )
    db_session.add_all([user_a, user_b])
    await db_session.flush()

    app_a = _build_app(db_session, {"id": str(user_a.id), "email": user_a.email})
    transport_a = httpx.ASGITransport(app=app_a)
    async with httpx.AsyncClient(transport=transport_a, base_url="http://test") as client:
        await client.post("/api/v1/subjects/", json={"name": "A's Subject"})

    app_b = _build_app(db_session, {"id": str(user_b.id), "email": user_b.email})
    transport_b = httpx.ASGITransport(app=app_b)
    async with httpx.AsyncClient(transport=transport_b, base_url="http://test") as client:
        resp = await client.get("/api/v1/subjects/")
        assert resp.json()["total"] == 0
