"""Pydantic schemas - manual-review-app study/quiz loop (flashcards + FSRS + corrections)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class FlashcardResponse(BaseModel):
    id: uuid.UUID
    subject_id: uuid.UUID
    topic_label: str
    front: str
    back: str
    due_at: datetime
    last_review_at: datetime | None


class FlashcardListResponse(BaseModel):
    items: list[FlashcardResponse]


class FlashcardReviewRequest(BaseModel):
    # fsrs.Rating: 1=Again, 2=Hard, 3=Good, 4=Easy.
    rating: int = Field(ge=1, le=4)
    # Whether the user's own self-assessed recall matched the real note
    # content shown after answering - the signal S65's corrections
    # pipeline captures (distinct from the FSRS rating, which only drives
    # scheduling).
    self_correct: bool
    consent_for_training: bool = False


class FlashcardReviewResponse(BaseModel):
    flashcard: FlashcardResponse
    correction_recorded: bool


class ReviewOutcome(BaseModel):
    flashcard_id: uuid.UUID
    rating: int
    reviewed_at: datetime


class StudyProgressResponse(BaseModel):
    subject_id: uuid.UUID
    total_reviews: int
    correct_reviews: int
    accuracy: float
    recent_outcomes: list[ReviewOutcome]
