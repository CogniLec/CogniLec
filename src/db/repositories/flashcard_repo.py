"""Flashcard repository (S58 storage, read/review paths for manual-review-app)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.flashcard import Flashcard, FlashcardReview


class FlashcardRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_subject(self, subject_id: uuid.UUID) -> list[Flashcard]:
        result = await self._session.execute(
            select(Flashcard).where(Flashcard.subject_id == subject_id).order_by(Flashcard.due_at)
        )
        return list(result.scalars().all())

    async def get(self, flashcard_id: uuid.UUID) -> Flashcard | None:
        return await self._session.get(Flashcard, flashcard_id)

    async def get_next_due(self, subject_id: uuid.UUID, now: datetime) -> Flashcard | None:
        """The most-overdue card, or the earliest not-yet-due one if none are due."""
        due_result = await self._session.execute(
            select(Flashcard)
            .where(Flashcard.subject_id == subject_id, Flashcard.due_at <= now)
            .order_by(Flashcard.due_at)
            .limit(1)
        )
        card = due_result.scalars().first()
        if card is not None:
            return card
        upcoming_result = await self._session.execute(
            select(Flashcard)
            .where(Flashcard.subject_id == subject_id)
            .order_by(Flashcard.due_at)
            .limit(1)
        )
        return upcoming_result.scalars().first()

    async def apply_review_fields(
        self, flashcard: Flashcard, fields: dict[str, object]
    ) -> Flashcard:
        for key, value in fields.items():
            setattr(flashcard, key, value)
        await self._session.flush()
        return flashcard

    async def record_review(self, flashcard_id: uuid.UUID, rating: int) -> FlashcardReview:
        review = FlashcardReview(flashcard_id=flashcard_id, rating=rating)
        self._session.add(review)
        await self._session.flush()
        return review

    async def list_reviews_for_subject(self, subject_id: uuid.UUID) -> list[FlashcardReview]:
        result = await self._session.execute(
            select(FlashcardReview)
            .join(Flashcard, Flashcard.id == FlashcardReview.flashcard_id)
            .where(Flashcard.subject_id == subject_id)
            .order_by(FlashcardReview.reviewed_at)
        )
        return list(result.scalars().all())
