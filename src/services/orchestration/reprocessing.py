"""S75 — scheduled reprocessing of stored sessions with newer prompts/models.

Reruns T6 (synthesis, `synthesize_notes_task`) and T7 (persist,
`persist_note_sections`) from `session_pipeline` (S47) against a session's
already-embedded utterances (`skip_embedding` semantics - T1-T3 are not
redone). `persist_note_sections` already upserts on `(session_id, topic_id,
ordinal)` (S45), so re-running it with a new `prompt_version` naturally
produces updated rows rather than duplicates (T75.1) - that guarantee comes
from S45's existing code, not new logic here.

T75.2 is the new guarantee this module adds: a user who has hand-edited a
note section (`corrections.correction_type = 'note_edit'`, S65) must not
have that edit silently overwritten by the next overnight reprocessing run.
`reprocess_session` looks up every `note_edit` correction's `source_id`
(the edited section's id) for the session up front and drops those
ordinals from the regenerated section list before persisting, so the
human-edited row is left untouched.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from src.services.orchestration.session_pipeline import FilterResult, synthesize_notes_task
from src.services.synthesis.note_persistence import persist_note_sections
from src.services.synthesis.note_synthesis import NoteSectionOutput, NoteSynthesisAgent


@dataclass
class ReprocessResult:
    sections_written: int
    sections_preserved: int


async def _user_edited_section_ids(db: AsyncSession, session_id: uuid.UUID) -> set[uuid.UUID]:
    """note_edit corrections whose source_id (a note_section id) belongs to this session."""
    rows = (
        await db.execute(
            text(
                "SELECT c.source_id FROM corrections c "
                "JOIN note_sections ns ON ns.id = c.source_id "
                "WHERE c.correction_type = 'note_edit' AND ns.session_id = :sid"
            ),
            {"sid": str(session_id)},
        )
    ).all()
    return {row[0] for row in rows if row[0] is not None}


async def reprocess_session(
    db: AsyncSession,
    session_id: uuid.UUID,
    subject_id: uuid.UUID,
    prompt_version: str,
    synthesis_agent: NoteSynthesisAgent,
    filter_result: FilterResult,
) -> ReprocessResult:
    """Re-run synthesis+persist for `session_id` under a newer `prompt_version`.

    Sections whose currently-persisted id appears as a `note_edit`
    correction's `source_id` are excluded from the write, preserving the
    human edit.
    """
    protected_section_ids = await _user_edited_section_ids(db, session_id)

    protected_ordinals: set[int] = set()
    if protected_section_ids:
        rows = (
            await db.execute(
                text(
                    "SELECT ordinal FROM note_sections WHERE session_id = :sid AND id = ANY(:ids)"
                ),
                {"sid": str(session_id), "ids": list(protected_section_ids)},
            )
        ).all()
        protected_ordinals = {row[0] for row in rows}

    new_sections: list[NoteSectionOutput] = await synthesize_notes_task.fn(
        session_id=session_id,
        subject_id=subject_id,
        prompt_version=prompt_version,
        db=db,
        synthesis_agent=synthesis_agent,
        filter_result=filter_result,
    )

    sections_to_write = [s for s in new_sections if s.ordinal not in protected_ordinals]
    preserved = len(new_sections) - len(sections_to_write)

    section_ids = await persist_note_sections(
        db=db,
        subject_id=subject_id,
        session_id=session_id,
        topic_id=None,
        sections=sections_to_write,
        model_version=prompt_version,
    )
    return ReprocessResult(sections_written=len(section_ids), sections_preserved=preserved)
