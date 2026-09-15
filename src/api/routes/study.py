"""FastAPI router - manual-review-app study/quiz loop.

Ties together S46 (notes), S58 (flashcards + FSRS scheduling) and S65
(corrections/training-signal capture) into the review loop the prototype
app needs: pick the next due flashcard for a subject, let the user answer
and self-rate against the real note content, persist the FSRS-scheduled
outcome, and - when the user's own recall didn't match - record that as a
`recall_mismatch` correction so it feeds the training-data flywheel.

Ownership is checked explicitly via `require_owned_subject` (not just
existence via RLS, which is bypassed in this environment — see
docs/gaps.md gap #4): `flashcards`/`flashcard_reviews` have no RLS policy
of their own, so access here is gated entirely by the subject ownership
check.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fsrs import Rating
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies.auth import get_current_user, get_db_session_with_rls
from src.api.dependencies.ownership import require_owned_subject
from src.api.schemas.study import (
    FlashcardListResponse,
    FlashcardResponse,
    FlashcardReviewRequest,
    FlashcardReviewResponse,
    ReviewOutcome,
    StudyProgressResponse,
)
from src.db.models.flashcard import Flashcard
from src.db.repositories.flashcard_repo import FlashcardRepository
from src.services.finetuning.corrections import capture_recall_mismatch
from src.services.study.fsrs_scheduler import new_card_fields
from src.services.study.fsrs_scheduler import review as fsrs_review

router = APIRouter(prefix="/subjects/{subject_id}", tags=["study"])


def _to_response(flashcard: Flashcard) -> FlashcardResponse:
    return FlashcardResponse(
        id=flashcard.id,
        subject_id=flashcard.subject_id,
        topic_label=flashcard.topic_label,
        front=flashcard.front,
        back=flashcard.back,
        due_at=flashcard.due_at,
        last_review_at=flashcard.last_review_at,
    )


@router.get("/flashcards", response_model=FlashcardListResponse)
async def list_flashcards(
    subject_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session_with_rls),
    current_user: dict[str, object] = Depends(get_current_user),
) -> FlashcardListResponse:
    await require_owned_subject(subject_id, db, current_user)
    cards = await FlashcardRepository(db).list_for_subject(subject_id)
    return FlashcardListResponse(items=[_to_response(c) for c in cards])


@router.get("/flashcards/next", response_model=FlashcardResponse)
async def get_next_flashcard(
    subject_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session_with_rls),
    current_user: dict[str, object] = Depends(get_current_user),
) -> FlashcardResponse:
    await require_owned_subject(subject_id, db, current_user)
    card = await FlashcardRepository(db).get_next_due(subject_id, datetime.now(UTC))
    if card is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No flashcards available for this subject yet",
        )
    return _to_response(card)


@router.post("/flashcards/{flashcard_id}/review", response_model=FlashcardReviewResponse)
async def review_flashcard(
    subject_id: uuid.UUID,
    flashcard_id: uuid.UUID,
    body: FlashcardReviewRequest,
    db: AsyncSession = Depends(get_db_session_with_rls),
    current_user: dict[str, object] = Depends(get_current_user),
) -> FlashcardReviewResponse:
    await require_owned_subject(subject_id, db, current_user)
    repo = FlashcardRepository(db)
    flashcard = await repo.get(flashcard_id)
    if flashcard is None or flashcard.subject_id != subject_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Flashcard not found")

    now = datetime.now(UTC)
    updated_fields = fsrs_review(flashcard, Rating(body.rating), review_datetime=now)
    await repo.apply_review_fields(flashcard, updated_fields)
    await repo.record_review(flashcard.id, body.rating)

    correction_recorded = False
    if not body.self_correct:
        await capture_recall_mismatch(
            db,
            subject_id=subject_id,
            user_id=uuid.UUID(str(current_user["id"])),
            flashcard_id=flashcard.id,
            front=flashcard.front,
            actual_back=flashcard.back,
            user_self_rating="incorrect",
            fsrs_rating=body.rating,
            consent_for_training=body.consent_for_training,
        )
        correction_recorded = True

    await db.commit()
    return FlashcardReviewResponse(
        flashcard=_to_response(flashcard), correction_recorded=correction_recorded
    )


@router.post(
    "/flashcards/seed", response_model=FlashcardResponse, status_code=status.HTTP_201_CREATED
)
async def seed_flashcard(
    subject_id: uuid.UUID,
    topic_label: str,
    front: str,
    back: str,
    db: AsyncSession = Depends(get_db_session_with_rls),
    current_user: dict[str, object] = Depends(get_current_user),
) -> FlashcardResponse:
    """Manually create a flashcard for a subject.

    A stopgap for this prototype: nothing in the pipeline yet calls S58's
    `FlashcardGenerator` automatically once notes are ready (see
    docs/gaps.md), so this lets a user (or a seed script) add a card by
    hand until that generation trigger exists.
    """
    await require_owned_subject(subject_id, db, current_user)
    flashcard = Flashcard(
        subject_id=subject_id,
        topic_label=topic_label,
        front=front,
        back=back,
        **new_card_fields(),
    )
    db.add(flashcard)
    await db.flush()
    await db.commit()
    return _to_response(flashcard)


@router.get("/study/progress", response_model=StudyProgressResponse)
async def get_study_progress(
    subject_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session_with_rls),
    current_user: dict[str, object] = Depends(get_current_user),
) -> StudyProgressResponse:
    await require_owned_subject(subject_id, db, current_user)
    reviews = await FlashcardRepository(db).list_reviews_for_subject(subject_id)
    total = len(reviews)
    correct = sum(1 for r in reviews if r.rating >= Rating.Good)
    accuracy = correct / total if total else 0.0
    recent = reviews[-20:]
    return StudyProgressResponse(
        subject_id=subject_id,
        total_reviews=total,
        correct_reviews=correct,
        accuracy=accuracy,
        recent_outcomes=[
            ReviewOutcome(flashcard_id=r.flashcard_id, rating=r.rating, reviewed_at=r.reviewed_at)
            for r in recent
        ],
    )
