"""Recovers sessions stuck at `recording` or `transcribed` with no automatic
retry path.

`reconcile_stale_recording_sessions`: finalization (`recording` ->
`transcribed`, then note/flashcard generation) normally only happens via
an `audio.processed` stream message flagged `final=true`, sent when the
client explicitly calls stop (see `src/workers/asr_worker.py`'s
`is_final` handling). If the recording tab crashes, loses network, or the
OS kills it before that message is sent -- confirmed live: a real
~20-minute lecture (441 already-transcribed utterances) sat at
`recording` for over a day with no failure_reason, because nothing ever
triggers finalization on its own -- the session is stuck forever even
though its audio was fully processed. The client's `beforeunload` guard
(docs/gaps.md #33i) only warns before an intentional close; it cannot run
at all on a crash or an OS-killed tab. This sweep finds `recording`
sessions idle past a threshold (no new utterance persisted recently) and
finalizes them the same way an explicit stop would -- or, if nothing was
ever transcribed, marks them FAILED instead of leaving them stuck
silently.

`reconcile_stale_transcribed_sessions`: confirmed live, this sweep's own
`recording` fix above surfaced a second gap immediately -- a session it
correctly finalized then had its note/flashcard generation call killed
outright by a container OOM (the local-embedding fallback path,
src/ml/embedding/client.py, on a 4GB container: see its own docstring and
docker-compose.yml's asr-worker memory comment) mid-task, with NO
exception logged (an OOM kill doesn't let Python's own handlers run) --
leaving the session stuck at `transcribed`, notes_ready=false, forever,
because `generate_study_materials` is normally only ever called once,
right after finalization, with no retry on any later failure regardless
of cause. Two real sessions were found stuck this way (423 minutes and
9.5 hours). This sweep retries generation for any such session, using
`sessions.retry_count`/`last_retry_at` (existing columns, already meant
for exactly this) to cap retries and avoid retrying a still-genuinely-
in-progress attempt.
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
# Deliberately longer than generate_study_materials' own 1800s (30min)
# bound (asr_worker.py's _generate_materials_bounded) so this never fires
# while a legitimate attempt might still genuinely be running -- there is
# no "generation in progress" flag to check instead, so idle time past a
# safe margin over that bound is the only signal available.
DEFAULT_TRANSCRIBED_IDLE_THRESHOLD = timedelta(minutes=45)
DEFAULT_MAX_MATERIALS_RETRIES = 3


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


async def reconcile_stale_transcribed_sessions(
    db: AsyncSession,
    idle_after: timedelta = DEFAULT_TRANSCRIBED_IDLE_THRESHOLD,
    max_retries: int = DEFAULT_MAX_MATERIALS_RETRIES,
) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """Finds `transcribed` sessions with notes_ready=false whose last
    attempt (or creation, if never retried) is older than `idle_after`,
    marks a new attempt (bumps `retry_count`, stamps `last_retry_at`), and
    returns (session_id, subject_id) pairs for the caller to run
    `generate_study_materials` on -- mirroring
    `reconcile_stale_recording_sessions`'s caller contract (this function
    only does the bookkeeping; the caller runs the actual retry).

    Capped at `max_retries` so a session that's genuinely, permanently
    broken (bad data, not a transient crash) doesn't get retried forever;
    past the cap it's left alone -- still visible via its stuck status for
    a human to investigate, not silently hidden or endlessly retried.
    """
    now = datetime.now(UTC)
    cutoff = now - idle_after

    rows = (
        await db.execute(
            select(
                Session.id,
                Session.subject_id,
                Session.created_at,
                Session.last_retry_at,
                Session.retry_count,
            ).where(
                Session.status == SessionStatus.TRANSCRIBED,
                Session.notes_ready.is_(False),
                Session.retry_count < max_retries,
            )
        )
    ).all()

    repo = SessionRepository(db)
    to_retry: list[tuple[uuid.UUID, uuid.UUID]] = []
    for session_id, subject_id, created_at, last_retry_at, retry_count in rows:
        last_attempt = last_retry_at or created_at
        if last_attempt > cutoff:
            continue  # still within generate_study_materials' own timeout window

        session_obj = await repo.get_or_raise(session_id)
        session_obj.last_retry_at = now
        session_obj.retry_count = retry_count + 1
        logger.warning(
            "reconciling stale transcribed session: retrying study-material generation",
            extra={"session_id": str(session_id), "attempt": retry_count + 1},
        )
        to_retry.append((session_id, subject_id))

    await db.commit()
    return to_retry
