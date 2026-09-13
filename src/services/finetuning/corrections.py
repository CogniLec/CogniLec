"""S65 — correction capture: the six hooks that feed the data flywheel.

Every function here does exactly two things in one call: apply the human
correction to the live row the user is looking at (T65.5 - a correction is
a real product feature, not just telemetry) and append a `Correction` row
recording the original prediction, the corrected value, and enough context
to reconstruct a training example later (S66-S69). The two effects happen
in the same DB transaction so they can never drift apart.

`Correction` rows are never updated or deleted here - T65.2's immutability
is enforced at the DB level (migration `c4e7f2a9b6d1`'s `ON UPDATE/DELETE
DO INSTEAD NOTHING` rules), so this module only ever inserts.
"""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.models.correction import Correction


class CorrectionType(StrEnum):
    A1_RELEVANCE_OVERRIDE = "a1_relevance_override"
    TOPIC_LABEL_EDIT = "topic_label_edit"
    TOPIC_SPLIT_MERGE = "topic_split_merge"
    SYLLABUS_ALIGNMENT = "syllabus_alignment"
    IMAGE_REJECTION = "image_rejection"
    NOTE_EDIT = "note_edit"
    RECALL_MISMATCH = "recall_mismatch"


async def _record(
    session: AsyncSession,
    correction_type: CorrectionType,
    *,
    subject_id: uuid.UUID | None,
    user_id: uuid.UUID | None,
    source_id: uuid.UUID | None,
    original_value: dict[str, Any],
    corrected_value: dict[str, Any],
    context: dict[str, Any] | None = None,
    consent_for_training: bool = False,
) -> Correction:
    correction = Correction(
        correction_type=correction_type.value,
        subject_id=subject_id,
        user_id=user_id,
        source_id=source_id,
        original_value=original_value,
        corrected_value=corrected_value,
        context=context or {},
        consent_for_training=consent_for_training,
    )
    session.add(correction)
    await session.flush()
    return correction


async def capture_a1_relevance_override(
    session: AsyncSession,
    *,
    subject_id: uuid.UUID,
    user_id: uuid.UUID,
    utterance_id: uuid.UUID,
    original_is_relevant: bool,
    corrected_is_relevant: bool,
    utterance_text: str,
    topic_label: str,
    outlier_score: float | None,
    consent_for_training: bool = False,
) -> Correction:
    """User overrides A1's relevance decision on one utterance."""
    await session.execute(
        text(
            "UPDATE utterances SET is_relevant = :val, filter_reason = 'user_override' "
            "WHERE id = :id"
        ),
        {"val": corrected_is_relevant, "id": str(utterance_id)},
    )
    return await _record(
        session,
        CorrectionType.A1_RELEVANCE_OVERRIDE,
        subject_id=subject_id,
        user_id=user_id,
        source_id=utterance_id,
        original_value={"is_relevant": original_is_relevant},
        corrected_value={"is_relevant": corrected_is_relevant},
        context={
            "utterance_text": utterance_text,
            "topic_label": topic_label,
            "outlier_score": outlier_score,
        },
        consent_for_training=consent_for_training,
    )


async def capture_topic_label_edit(
    session: AsyncSession,
    *,
    subject_id: uuid.UUID,
    user_id: uuid.UUID,
    topic_id: uuid.UUID,
    original_label: str | None,
    corrected_label: str,
    keywords: list[str] | None,
    consent_for_training: bool = False,
) -> Correction:
    """User edits an S31 auto-generated topic label (S31)."""
    await session.execute(
        text(
            "UPDATE topics SET label = :label, is_user_edited = true "
            "WHERE id = :id AND subject_id = :subject_id"
        ),
        {"label": corrected_label, "id": str(topic_id), "subject_id": str(subject_id)},
    )
    return await _record(
        session,
        CorrectionType.TOPIC_LABEL_EDIT,
        subject_id=subject_id,
        user_id=user_id,
        source_id=topic_id,
        original_value={"label": original_label},
        corrected_value={"label": corrected_label},
        context={"keywords": keywords or []},
        consent_for_training=consent_for_training,
    )


async def capture_topic_split_merge(
    session: AsyncSession,
    *,
    subject_id: uuid.UUID,
    user_id: uuid.UUID,
    original_topic_ids: list[uuid.UUID],
    resulting_topic_ids: list[uuid.UUID],
    operation: str,
    consent_for_training: bool = False,
) -> Correction:
    """User splits or merges topic clusters produced by S30's clustering."""
    if operation not in ("split", "merge"):
        msg = f"operation must be 'split' or 'merge', got {operation!r}"
        raise ValueError(msg)
    return await _record(
        session,
        CorrectionType.TOPIC_SPLIT_MERGE,
        subject_id=subject_id,
        user_id=user_id,
        source_id=original_topic_ids[0] if original_topic_ids else None,
        original_value={"topic_ids": [str(t) for t in original_topic_ids]},
        corrected_value={"topic_ids": [str(t) for t in resulting_topic_ids]},
        context={"operation": operation},
        consent_for_training=consent_for_training,
    )


async def capture_syllabus_alignment_correction(
    session: AsyncSession,
    *,
    subject_id: uuid.UUID,
    user_id: uuid.UUID,
    syllabus_item_id: uuid.UUID,
    original_topic_id: uuid.UUID | None,
    corrected_topic_id: uuid.UUID | None,
    syllabus_item_text: str,
    consent_for_training: bool = False,
) -> Correction:
    """User corrects an S52 syllabus-to-topic alignment."""
    return await _record(
        session,
        CorrectionType.SYLLABUS_ALIGNMENT,
        subject_id=subject_id,
        user_id=user_id,
        source_id=syllabus_item_id,
        original_value={"topic_id": str(original_topic_id) if original_topic_id else None},
        corrected_value={"topic_id": str(corrected_topic_id) if corrected_topic_id else None},
        context={"syllabus_item_text": syllabus_item_text},
        consent_for_training=consent_for_training,
    )


async def capture_image_rejection(
    session: AsyncSession,
    *,
    subject_id: uuid.UUID,
    user_id: uuid.UUID,
    image_id: uuid.UUID,
    concept_description: str,
    rejection_reason: str,
    consent_for_training: bool = False,
) -> Correction:
    """User rejects an S62/S63 retrieved or generated image."""
    return await _record(
        session,
        CorrectionType.IMAGE_REJECTION,
        subject_id=subject_id,
        user_id=user_id,
        source_id=image_id,
        original_value={"accepted": True},
        corrected_value={"accepted": False, "reason": rejection_reason},
        context={"concept_description": concept_description},
        consent_for_training=consent_for_training,
    )


async def capture_note_edit(
    session: AsyncSession,
    *,
    subject_id: uuid.UUID,
    user_id: uuid.UUID,
    note_section_id: uuid.UUID,
    original_body_md: str,
    corrected_body_md: str,
    heading: str,
    consent_for_training: bool = False,
) -> Correction:
    """User edits a generated note section's body (S43's A2 output)."""
    await session.execute(
        text("UPDATE note_sections SET body_md = :body WHERE id = :id"),
        {"body": corrected_body_md, "id": str(note_section_id)},
    )
    return await _record(
        session,
        CorrectionType.NOTE_EDIT,
        subject_id=subject_id,
        user_id=user_id,
        source_id=note_section_id,
        original_value={"body_md": original_body_md},
        corrected_value={"body_md": corrected_body_md},
        context={"heading": heading},
        consent_for_training=consent_for_training,
    )


async def capture_recall_mismatch(
    session: AsyncSession,
    *,
    subject_id: uuid.UUID,
    user_id: uuid.UUID,
    flashcard_id: uuid.UUID,
    front: str,
    actual_back: str,
    user_self_rating: str,
    fsrs_rating: int,
    consent_for_training: bool = False,
) -> Correction:
    """User reviews a flashcard against the real note and marks their own recall wrong.

    This is the manual-review-app's quiz/recall loop feeding S65: no row is
    updated (unlike the other capture hooks) - the flashcard's own state is
    already updated separately by S58's FSRS scheduler in the same request,
    this only records the training signal.
    """
    return await _record(
        session,
        CorrectionType.RECALL_MISMATCH,
        subject_id=subject_id,
        user_id=user_id,
        source_id=flashcard_id,
        original_value={"expected_back": actual_back},
        corrected_value={"user_self_rating": user_self_rating},
        context={"front": front, "fsrs_rating": fsrs_rating},
        consent_for_training=consent_for_training,
    )
