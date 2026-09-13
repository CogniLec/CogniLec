"""S58 — FSRS spaced-repetition scheduling, via the real `fsrs` (py-fsrs) package.

The spec (T58.2) checks scheduling "against a reference implementation" -
`py-fsrs` (https://pypi.org/project/fsrs/) implements the published FSRS
algorithm and is exactly that reference implementation, not a
reimplementation of our own that could honestly claim to match it, so it is
used directly rather than hand-rolled (see pyproject.toml).

`Flashcard` (the ORM row) stores the subset of `fsrs.Card`'s fields needed
to reconstruct one exactly: state/step/stability/difficulty/due/last_review.
`card_id` is not persisted - it is only used by the library to key its own
optimizer/review-log bookkeeping, which this module doesn't use.
"""

from __future__ import annotations

from datetime import datetime

from fsrs import Card, Rating, Scheduler, State
from src.db.models.flashcard import Flashcard

# `enable_fuzzing=False`: py-fsrs's default randomises due dates slightly
# (anti-clustering for large decks). Disabled here for determinism - two
# reviews of the same card with the same rating and `review_datetime` must
# produce the same schedule (T58.2 checks this against a reference
# `Scheduler()` call, which would otherwise disagree run-to-run purely from
# fuzzing's own RNG, not from any real scheduling difference).
_scheduler = Scheduler(enable_fuzzing=False)


def new_card_fields() -> dict[str, object]:
    """Field values for a freshly created flashcard (never yet reviewed)."""
    card = Card()
    return _card_to_fields(card)


def _card_to_fields(card: Card) -> dict[str, object]:
    return {
        "fsrs_state": int(card.state),
        "fsrs_step": card.step,
        "fsrs_stability": card.stability,
        "fsrs_difficulty": card.difficulty,
        "due_at": card.due,
        "last_review_at": card.last_review,
    }


def _flashcard_to_card(flashcard: Flashcard) -> Card:
    return Card(
        state=State(flashcard.fsrs_state),
        step=flashcard.fsrs_step,
        stability=flashcard.fsrs_stability,
        difficulty=flashcard.fsrs_difficulty,
        due=flashcard.due_at,
        last_review=flashcard.last_review_at,
    )


def review(
    flashcard: Flashcard, rating: Rating, review_datetime: datetime | None = None
) -> dict[str, object]:
    """Apply one review to `flashcard`'s FSRS state and return the updated fields.

    Does not mutate or persist `flashcard` itself - the caller assigns the
    returned fields and commits, keeping this module free of any DB access
    (T58.3's persistence step lives in the repository layer, not here).
    """
    card = _flashcard_to_card(flashcard)
    updated_card, _log = _scheduler.review_card(card, rating, review_datetime=review_datetime)
    return _card_to_fields(updated_card)


def retrievability(flashcard: Flashcard, at: datetime | None = None) -> float:
    """Current recall probability estimate for `flashcard` (0-1)."""
    card = _flashcard_to_card(flashcard)
    return float(card.get_retrievability(current_datetime=at))


__all__ = ["Card", "Rating", "Scheduler", "State", "new_card_fields", "retrievability", "review"]
