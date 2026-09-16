"""Tests for the S24 transcript read API (T24.1, T24.2, T24.5).

T24.3 (client audio-seek within 500ms) and T24.4 (human review of real
lecture sessions) require a real browser/client and real lecture audio;
they are not exercisable as a backend pytest integration test and are
marked skip below with that reason, mirroring the pattern already
established in tests/test_diarisation.py and tests/test_e2e_gate.py.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from src.api.dependencies.auth import get_current_user
from src.api.dependencies.database import get_db_session
from src.api.routes.transcript import router as transcript_router
from src.db.models.subject import Subject
from src.db.models.user import User
from src.db.partitions.provisioner import PartitionProvisioner
from src.db.repositories.session_repo import SessionRepository
from src.db.repositories.utterance_repo import UtteranceRepository

pytestmark = pytest.mark.integration

# gap #4 fix: `lis_app` (NOSUPERUSER NOBYPASSRLS, migration
# c4d8e2a6f1b9) -- connecting as this role instead of the superuser `lis`
# used by the `db_session` fixture is what actually makes RLS enforcement
# testable; see TestT242RLSCrossUserBlocked below. Points at lis_test, the
# same isolated database the db_session fixture itself uses (conftest.py)
# -- not lis_main, the live app's real database.
_RLS_ROLE_DATABASE_URL = "postgresql+asyncpg://lis_app:lis_app_dev@localhost:5434/lis_test"


async def _create_user_and_subject(
    session: AsyncSession, email: str | None = None
) -> tuple[User, Subject]:
    user = User(
        email=email or f"test-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="h",
        is_active=True,
    )
    session.add(user)
    await session.flush()
    provisioner = PartitionProvisioner()
    subject = await provisioner.provision_subject(session, user.id, name="Test Subject")
    return user, subject


def _build_app(db_session: AsyncSession, current_user: dict[str, Any]) -> FastAPI:
    app = FastAPI()
    app.include_router(transcript_router, prefix="/api/v1")

    async def _override_db() -> AsyncSession:
        return db_session

    async def _override_user() -> dict[str, Any]:
        return current_user

    app.dependency_overrides[get_db_session] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    return app


async def _seed_utterances(
    db_session: AsyncSession, subject: Subject, session_id: uuid.UUID, count: int
) -> None:
    utterance_repo = UtteranceRepository(db_session)
    rows = [
        {
            "session_id": session_id,
            "seq": i,
            "start_ms": i * 1000,
            "end_ms": i * 1000 + 900,
            "text": f"utterance number {i}",
            "asr_confidence": 0.9,
            "words": [],
            "speaker_tag": "SPK_A",
            "embed_model_ver": "test-v1",
        }
        for i in range(count)
    ]
    await utterance_repo.bulk_insert(subject.id, rows)
    await db_session.commit()


class TestT241Pagination:
    async def test_pages_return_correct_counts_no_duplicates(
        self, db_session: AsyncSession
    ) -> None:
        user, subject = await _create_user_and_subject(db_session)
        session_repo = SessionRepository(db_session)
        session_obj = await session_repo.create(subject.id)
        await db_session.commit()
        await _seed_utterances(db_session, subject, session_obj.id, 200)

        app = _build_app(db_session, {"id": user.id, "email": user.email, "is_active": True})
        transport = httpx.ASGITransport(app=app)
        seen_ids: set[str] = set()
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            for page in range(4):
                resp = await client.get(
                    f"/api/v1/sessions/{session_obj.id}/transcript",
                    params={"offset": page * 50, "limit": 50},
                    headers={"Authorization": "Bearer fake"},
                )
                assert resp.status_code == 200
                body = resp.json()
                assert body["total_utterances"] == 200
                assert len(body["utterances"]) == 50
                assert body["offset"] == page * 50
                for utt in body["utterances"]:
                    assert utt["id"] not in seen_ids
                    seen_ids.add(utt["id"])
        assert len(seen_ids) == 200


class TestT242RLSCrossUserBlocked:
    async def test_route_returns_404_not_403_when_session_missing(
        self, db_session: AsyncSession
    ) -> None:
        """Mechanical half of T24.2: a session id that does not resolve for
        the current RLS context (here: simply does not exist) returns 404
        with a non-leaking detail message, never 403. See the module-level
        skip below for why the full cross-user RLS enforcement path is not
        exercised in this environment."""
        user, _ = await _create_user_and_subject(db_session)
        app = _build_app(db_session, {"id": user.id, "email": user.email, "is_active": True})
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                f"/api/v1/sessions/{uuid.uuid4()}/transcript",
                headers={"Authorization": "Bearer fake"},
            )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Session not found"

    async def test_other_users_session_returns_404_not_403(self, db_session: AsyncSession) -> None:
        """T24.2, now exercising real RLS denial (gap #4 fix).

        Seeding still goes through the superuser `db_session` fixture (its
        schema-reset/migration setup needs DDL rights), but the actual HTTP
        request below is served through a `lis_app`-connected session
        (NOSUPERUSER NOBYPASSRLS) -- the same role the app now uses at
        runtime (src/api/dependencies/database.py). Postgres itself, not
        application code, is what denies the intruder's read here.
        """
        _owner, owner_subject = await _create_user_and_subject(db_session)
        session_repo = SessionRepository(db_session)
        session_obj = await session_repo.create(owner_subject.id)
        await db_session.commit()
        await _seed_utterances(db_session, owner_subject, session_obj.id, 3)

        intruder, _ = await _create_user_and_subject(db_session)
        await db_session.commit()

        rls_engine = create_async_engine(_RLS_ROLE_DATABASE_URL, echo=False)
        rls_session_factory = async_sessionmaker(
            rls_engine, class_=AsyncSession, expire_on_commit=False
        )
        try:
            async with rls_session_factory() as rls_session:
                app = _build_app(
                    rls_session, {"id": intruder.id, "email": intruder.email, "is_active": True}
                )
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                    resp = await client.get(
                        f"/api/v1/sessions/{session_obj.id}/transcript",
                        headers={"Authorization": "Bearer fake"},
                    )
        finally:
            await rls_engine.dispose()

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Session not found"


class TestT245PerformanceBudget:
    async def test_first_page_loads_under_one_second(self, db_session: AsyncSession) -> None:
        user, subject = await _create_user_and_subject(db_session)
        session_repo = SessionRepository(db_session)
        session_obj = await session_repo.create(subject.id)
        await db_session.commit()
        await _seed_utterances(db_session, subject, session_obj.id, 600)

        app = _build_app(db_session, {"id": user.id, "email": user.email, "is_active": True})
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            start = time.monotonic()
            resp = await client.get(
                f"/api/v1/sessions/{session_obj.id}/transcript",
                params={"offset": 0, "limit": 50},
                headers={"Authorization": "Bearer fake"},
            )
            elapsed = time.monotonic() - start
        assert resp.status_code == 200
        assert len(resp.json()["utterances"]) == 50
        assert elapsed < 1.0


@pytest.mark.skip(
    reason="T24.3 requires a real browser running the wavesurfer.js client "
    "view against real audio to measure seek latency; not exercisable as a "
    "backend pytest integration test."
)
def test_t24_3_click_utterance_seeks_audio_within_500ms() -> None:
    pass


@pytest.mark.skip(
    reason="T24.4 is a manual (M) human-review test spec requiring 3 real "
    "lecture sessions and a human reviewer listening while reading the "
    "transcript; not automatable."
)
def test_t24_4_human_review_transcript_readability() -> None:
    pass
