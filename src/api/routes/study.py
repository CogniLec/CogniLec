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
    StudyStatusResponse,
)
from src.db.models.flashcard import Flashcard
from src.db.repositories.flashcard_repo import FlashcardRepository
from src.db.repositories.session_repo import SessionRepository
from src.services.finetuning.corrections import capture_recall_mismatch
from src.services.orchestration.auto_study_materials import (
    build_llm_router,
    generate_flashcards_for_subject,
)
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
    "/flashcards/generate",
    response_model=FlashcardListResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_flashcards(
    subject_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session_with_rls),
    current_user: dict[str, object] = Depends(get_current_user),
) -> FlashcardListResponse:
    """Generate real flashcards on demand from a subject's already-
    persisted notes/topics.

    Replaces the old `seed_flashcard` manual-entry stopgap (removed
    2026-09-17): that endpoint let a user type a flashcard's front/back
    text by hand, with no LLM involved, because nothing in the pipeline
    called S58's `FlashcardGenerator` automatically yet. That auto-trigger
    now exists (`src/services/orchestration/auto_study_materials.py`,
    wired since docs/gaps.md gap #33) and fires after every recording, but
    a user may still want to (re)generate flashcards for a subject on
    demand -- e.g. after editing notes, or for a subject whose auto-
    generation produced nothing the first time. Reuses the exact same
    generation logic as the auto-trigger path
    (`generate_flashcards_for_subject`), just without needing a specific
    session_id.
    """
    await require_owned_subject(subject_id, db, current_user)
    router = build_llm_router()
    created = await generate_flashcards_for_subject(db, subject_id, router)
    if created == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "No flashcards could be generated -- this subject has no persisted "
                "notes/topics yet, or generation failed for all of them."
            ),
        )
    cards = await FlashcardRepository(db).list_for_subject(subject_id)
    return FlashcardListResponse(items=[_to_response(c) for c in cards])


@router.get("/study/status", response_model=StudyStatusResponse)
async def get_study_status(
    subject_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session_with_rls),
    current_user: dict[str, object] = Depends(get_current_user),
) -> StudyStatusResponse:
    """Lets the frontend poll for whether the most recent recording's
    notes/flashcards are ready, instead of the user having to manually
    reload the Review tab and guess (docs/gaps.md #33f) -- generation
    itself already runs automatically after transcription
    (`src/workers/asr_worker.py`), this just surfaces its progress.
    """
    await require_owned_subject(subject_id, db, current_user)
    latest_session = await SessionRepository(db).get_latest_for_subject(subject_id)
    flashcards = await FlashcardRepository(db).list_for_subject(subject_id)
    return StudyStatusResponse(
        subject_id=subject_id,
        session_id=latest_session.id if latest_session else None,
        status=latest_session.status if latest_session else None,
        notes_ready=latest_session.notes_ready if latest_session else False,
        flashcard_count=len(flashcards),
        failure_reason=latest_session.failure_reason if latest_session else None,
    )


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
