"""Tests for the manual-review-app study/quiz loop (flashcards + FSRS + S65 corrections).

Exercises the real end-to-end loop: a flashcard exists for a subject
(created directly via DB fixture -- see `_create_flashcard` below; the
`POST .../flashcards/seed` manual-entry endpoint these tests used to call
was removed 2026-09-17 in favor of a real generate-from-notes endpoint,
docs/gaps.md), fetch it as the next-due card, submit a review, and confirm
both S58's FSRS scheduling state and S65's corrections table reflect it.

Requires two real user accounts interacting through the live auth flow to
be exercised in a browser (a genuine multi-user session) - not possible
against this pytest DB-fixture setup, so cross-user isolation here is
checked at the API layer (RLS 404) with two DB-created users rather than
two live logged-in sessions; see docs/gaps.md.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.api.dependencies.auth import get_current_user
from src.api.dependencies.database import get_db_session
from src.api.routes.study import router as study_router
from src.db.models.correction import Correction
from src.db.models.flashcard import Flashcard, FlashcardReview
from src.db.models.subject import Subject
from src.db.models.user import User
from src.db.partitions.provisioner import PartitionProvisioner
from src.services.study.fsrs_scheduler import new_card_fields

pytestmark = pytest.mark.integration


async def _create_user_and_subject(session: AsyncSession) -> tuple[User, Subject]:
    user = User(email=f"t-{uuid.uuid4().hex[:8]}@example.com", hashed_password="h", is_active=True)
    session.add(user)
    await session.flush()
    subject = await PartitionProvisioner().provision_subject(session, user.id, name="Subj")
    return user, subject


async def _create_flashcard(
    session: AsyncSession, subject_id: uuid.UUID, topic_label: str, front: str, back: str
) -> Flashcard:
    """Direct DB fixture creation, replacing the removed `/flashcards/seed`
    manual-entry endpoint as test setup (docs/gaps.md)."""
    flashcard = Flashcard(
        subject_id=subject_id,
        topic_label=topic_label,
        front=front,
        back=back,
        **new_card_fields(),
    )
    session.add(flashcard)
    await session.flush()
    return flashcard


def _build_app(db_session: AsyncSession, current_user: dict[str, Any]) -> FastAPI:
    app = FastAPI()
    app.include_router(study_router, prefix="/api/v1")

    async def _override_db() -> AsyncSession:
        return db_session

    async def _override_user() -> dict[str, Any]:
        return current_user

    app.dependency_overrides[get_db_session] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    return app


@pytest.mark.asyncio
async def test_seed_and_next_due_flashcard(db_session: AsyncSession) -> None:
    user, subject = await _create_user_and_subject(db_session)
    await _create_flashcard(
        db_session, subject.id, "Photosynthesis", "What is it?", "Light -> sugar"
    )
    await db_session.commit()

    app = _build_app(db_session, {"id": str(user.id), "email": user.email, "is_active": True})
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        next_resp = await client.get(f"/api/v1/subjects/{subject.id}/flashcards/next")

    assert next_resp.status_code == 200
    body = next_resp.json()
    assert body["front"] == "What is it?"
    assert body["back"] == "Light -> sugar"


@pytest.mark.asyncio
async def test_review_correct_updates_fsrs_state_without_correction(
    db_session: AsyncSession,
) -> None:
    user, subject = await _create_user_and_subject(db_session)
    flashcard = await _create_flashcard(db_session, subject.id, "T", "Q", "A")
    await db_session.commit()
    flashcard_id = str(flashcard.id)
    app = _build_app(db_session, {"id": str(user.id), "email": user.email, "is_active": True})
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        review_resp = await client.post(
            f"/api/v1/subjects/{subject.id}/flashcards/{flashcard_id}/review",
            json={"rating": 3, "self_correct": True},
        )

    assert review_resp.status_code == 200
    body = review_resp.json()
    assert body["correction_recorded"] is False

    flashcard = await db_session.get(Flashcard, uuid.UUID(flashcard_id))
    assert flashcard is not None
    assert flashcard.last_review_at is not None

    reviews = (
        (
            await db_session.execute(
                select(FlashcardReview).where(FlashcardReview.flashcard_id == flashcard.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(reviews) == 1
    assert reviews[0].rating == 3

    corrections = (
        (await db_session.execute(select(Correction).where(Correction.subject_id == subject.id)))
        .scalars()
        .all()
    )
    assert corrections == []


@pytest.mark.asyncio
async def test_review_incorrect_records_recall_mismatch_correction(
    db_session: AsyncSession,
) -> None:
    """The core loop this app adds: wrong self-rated recall feeds S65."""
    user, subject = await _create_user_and_subject(db_session)
    flashcard = await _create_flashcard(db_session, subject.id, "T", "Q", "The real answer")
    await db_session.commit()
    flashcard_id = str(flashcard.id)
    app = _build_app(db_session, {"id": str(user.id), "email": user.email, "is_active": True})
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        review_resp = await client.post(
            f"/api/v1/subjects/{subject.id}/flashcards/{flashcard_id}/review",
            json={"rating": 1, "self_correct": False, "consent_for_training": True},
        )

    assert review_resp.status_code == 200
    assert review_resp.json()["correction_recorded"] is True

    corrections = (
        (await db_session.execute(select(Correction).where(Correction.subject_id == subject.id)))
        .scalars()
        .all()
    )
    assert len(corrections) == 1
    correction = corrections[0]
    assert correction.correction_type == "recall_mismatch"
    assert correction.user_id == user.id
    assert correction.original_value == {"expected_back": "The real answer"}
    assert correction.consent_for_training is True


@pytest.mark.asyncio
async def test_study_progress_reflects_review_history(db_session: AsyncSession) -> None:
    user, subject = await _create_user_and_subject(db_session)
    flashcard = await _create_flashcard(db_session, subject.id, "T", "Q", "A")
    await db_session.commit()
    flashcard_id = str(flashcard.id)
    app = _build_app(db_session, {"id": str(user.id), "email": user.email, "is_active": True})
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post(
            f"/api/v1/subjects/{subject.id}/flashcards/{flashcard_id}/review",
            json={"rating": 4, "self_correct": True},
        )
        await client.post(
            f"/api/v1/subjects/{subject.id}/flashcards/{flashcard_id}/review",
            json={"rating": 1, "self_correct": False},
        )

        progress_resp = await client.get(f"/api/v1/subjects/{subject.id}/study/progress")

    assert progress_resp.status_code == 200
    body = progress_resp.json()
    assert body["total_reviews"] == 2
    assert body["correct_reviews"] == 1
    assert body["accuracy"] == 0.5
    assert len(body["recent_outcomes"]) == 2


@pytest.mark.asyncio
async def test_flashcards_from_other_users_subject_returns_404(
    db_session: AsyncSession,
) -> None:
    """Regression test for a live-audit finding (docs/gaps.md): `study.py`
    used to check only that a subject existed (`SubjectRepository.get_or_raise`),
    never that it belonged to the caller, relying entirely on RLS -- which is
    bypassed under the dev role (gap #4). `require_owned_subject` now checks
    ownership explicitly and independent of RLS, so a cross-user request
    genuinely 404s regardless of the RLS/superuser gap.
    """
    _owner, subject = await _create_user_and_subject(db_session)
    intruder = User(
        email=f"i-{uuid.uuid4().hex[:8]}@example.com", hashed_password="h", is_active=True
    )
    db_session.add(intruder)
    await db_session.flush()
    await db_session.commit()

    app = _build_app(
        db_session, {"id": str(intruder.id), "email": intruder.email, "is_active": True}
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/v1/subjects/{subject.id}/flashcards")

    assert resp.status_code == 404
