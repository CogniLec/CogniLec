"""Tests for S52 T52.2 — subject dashboard (AC-14: taught vs outstanding)."""

from __future__ import annotations

import uuid

import httpx
import pytest
from fastapi import FastAPI
from src.api.dependencies.auth import get_current_user
from src.api.dependencies.database import get_db_session, get_syllabus_db_session
from src.api.routes.dashboard import router as dashboard_router
from src.db.models.syllabus_item import SyllabusItem
from src.db.models.user import User
from src.db.repositories.subject_repo import SubjectRepository

pytestmark = pytest.mark.integration


async def test_dashboard_teached_vs_outstanding(syllabus_session, db_session) -> None:
    """T52.2 / AC-14: dashboard reports total/covered/partial/not_started correctly."""
    user = User(email=f"d-{uuid.uuid4().hex[:8]}@example.com", hashed_password="h", is_active=True)
    db_session.add(user)
    await db_session.flush()
    subject = await SubjectRepository(db_session).create(user.id, "Dashboard Subject")
    await db_session.commit()

    for i in range(8):
        syllabus_session.add(
            SyllabusItem(
                subject_id=subject.id,
                ordinal=i,
                title=f"Covered {i}",
                item_type="topic",
                coverage_status="covered",
            )
        )
    for i in range(5):
        syllabus_session.add(
            SyllabusItem(
                subject_id=subject.id,
                ordinal=8 + i,
                title=f"Partial {i}",
                item_type="topic",
                coverage_status="partial",
            )
        )
    for i in range(7):
        syllabus_session.add(
            SyllabusItem(
                subject_id=subject.id,
                ordinal=13 + i,
                title=f"NotStarted {i}",
                item_type="topic",
                coverage_status="not_started",
            )
        )
    await syllabus_session.commit()

    app = FastAPI()
    app.include_router(dashboard_router, prefix="/api/v1")
    app.dependency_overrides[get_syllabus_db_session] = lambda: syllabus_session
    app.dependency_overrides[get_db_session] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: {"id": str(user.id), "email": user.email}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/v1/subjects/{subject.id}/dashboard")

    assert resp.status_code == 200
    body = resp.json()
    coverage = body["coverage"]
    assert coverage["total_items"] == 20
    assert coverage["covered_items"] == 8
    assert coverage["partial_items"] == 5
    assert coverage["not_started_items"] == 7
    assert coverage["coverage_pct"] == 40.0
