"""Recovers sessions stuck at `recording` because they were never finalized.

Finalization (`recording` -> `transcribed`, then note/flashcard generation)
normally only happens via an `audio.processed` stream message flagged
`final=true`, sent when the client explicitly calls stop (see
`src/workers/asr_worker.py`'s `is_final` handling). If the recording tab
crashes, loses network, or the OS kills it before that message is sent
-- confirmed live: a real ~20-minute lecture (441 already-transcribed
utterances) sat at `recording` for over a day with no failure_reason,
because nothing ever triggers finalization on its own -- the session is
stuck forever even though its audio was fully processed. The client's
`beforeunload` guard (docs/gaps.md #33i) only warns before an intentional
close; it cannot run at all on a crash or an OS-killed tab.

This sweep finds `recording` sessions idle past a threshold (no new
utterance persisted recently) and finalizes them the same way an
explicit stop would -- or, if nothing was ever transcribed, marks them
FAILED instead of leaving them stuck silently.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.models.session import Session, SessionStatus
from src.db.models.utterance import Utterance
from src.db.repositories.session_repo import SessionRepository

logger = logging.getLogger(__name__)

DEFAULT_IDLE_THRESHOLD = timedelta(minutes=15)


@dataclass(frozen=True)
class ReconciliationResult:
    finalized_session_ids: list[tuple[uuid.UUID, uuid.UUID]]  # (session_id, subject_id)
    failed_session_ids: list[uuid.UUID]


async def reconcile_stale_recording_sessions(
    db: AsyncSession, idle_after: timedelta = DEFAULT_IDLE_THRESHOLD
) -> ReconciliationResult:
    """Finalizes or fails every `recording` session idle past `idle_after`.

    Idle is measured from the most recent utterance actually persisted for
    that session (real activity), falling back to the session's own
    `created_at` when it has none at all -- a session's `updated_at`
    isn't a reliable signal here since nothing in this codebase bumps it
    on each chunk (no `onupdate`). Caller commits and, for each finalized
    (session_id, subject_id) pair, is expected to trigger
    `generate_study_materials` exactly as the normal `is_final` path does
    -- this function only performs the status transition, mirroring
    `ASRWorker._finalize_session`'s own division of responsibility.
    """
    now = datetime.now(UTC)
    cutoff = now - idle_after

    stale_rows = (
        await db.execute(
            select(
                Session.id,
                Session.subject_id,
                Session.created_at,
                func.max(Utterance.created_at).label("last_utterance_at"),
            )
            .outerjoin(
                Utterance,
                (Utterance.session_id == Session.id) & (Utterance.subject_id == Session.subject_id),
            )
            .where(Session.status == SessionStatus.RECORDING)
            .group_by(Session.id, Session.subject_id, Session.created_at)
        )
    ).all()

    finalized: list[tuple[uuid.UUID, uuid.UUID]] = []
    failed: list[uuid.UUID] = []
    repo = SessionRepository(db)

    for session_id, subject_id, created_at, last_utterance_at in stale_rows:
        last_activity = last_utterance_at or created_at
        if last_activity > cutoff:
            continue  # still plausibly an active recording

        session_obj = await repo.get_or_raise(session_id)
        if last_utterance_at is not None:
            logger.warning(
                "reconciling stale recording session: finalizing (had transcribed audio)",
                extra={"session_id": str(session_id), "last_utterance_at": str(last_utterance_at)},
            )
            await repo.update_status(session_obj, SessionStatus.TRANSCRIBED)
            finalized.append((session_id, subject_id))
        else:
            logger.warning(
                "reconciling stale recording session: marking failed (no audio ever received)",
                extra={"session_id": str(session_id)},
            )
            session_obj.status = SessionStatus.FAILED
            session_obj.failure_reason = (
                "Recording was never stopped and no audio chunks were ever received "
                "-- likely the tab closed, crashed, or lost network before any audio "
                "was captured."
            )
            session_obj.failure_stage = "recording"
            failed.append(session_id)

    await db.commit()
    return ReconciliationResult(finalized_session_ids=finalized, failed_session_ids=failed)
