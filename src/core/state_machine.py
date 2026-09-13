"""SessionStateMachine - centralised session status transitions (S23).

All session status changes MUST go through `SessionStateMachine.transition()`.
Direct `session.status = X` assignments elsewhere are forbidden per the S23
spec; `SessionRepository.update_status()` remains for backward compatibility
with pre-S23 callers but new code should use this state machine.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession
from src.db.exceptions import InvalidTransitionError
from src.db.models.session import Session, SessionStatus

logger = logging.getLogger(__name__)

# Exhaustive set of legal (from, to) transitions. Any pair not present here
# is rejected. `None` as the guard means "no additional guard beyond a valid
# from/to state" (guards are enforced by callers passing a `reason`, not by
# this map - kept as a set for simplicity per the spec's matrix).
TRANSITIONS: frozenset[tuple[SessionStatus, SessionStatus]] = frozenset(
    {
        (SessionStatus.CREATED, SessionStatus.RECORDING),
        (SessionStatus.RECORDING, SessionStatus.TRANSCRIBED),
        (SessionStatus.TRANSCRIBED, SessionStatus.PROCESSING),
        (SessionStatus.PROCESSING, SessionStatus.COMPLETE),
        (SessionStatus.PROCESSING, SessionStatus.FAILED),
        (SessionStatus.FAILED, SessionStatus.PROCESSING),
        (SessionStatus.FAILED, SessionStatus.TRANSCRIBED),
        (SessionStatus.CREATED, SessionStatus.FAILED),
        (SessionStatus.RECORDING, SessionStatus.FAILED),
    }
)

_EVENT_NAMES: dict[tuple[SessionStatus, SessionStatus], str] = {
    (SessionStatus.CREATED, SessionStatus.RECORDING): "session.recording_started",
    (SessionStatus.RECORDING, SessionStatus.TRANSCRIBED): "session.transcribed",
    (SessionStatus.TRANSCRIBED, SessionStatus.PROCESSING): "session.processing_started",
    (SessionStatus.PROCESSING, SessionStatus.COMPLETE): "session.completed",
    (SessionStatus.PROCESSING, SessionStatus.FAILED): "session.failed",
    (SessionStatus.FAILED, SessionStatus.PROCESSING): "session.retry_started",
    (SessionStatus.FAILED, SessionStatus.TRANSCRIBED): "session.re_asr_started",
    (SessionStatus.CREATED, SessionStatus.FAILED): "session.failed",
    (SessionStatus.RECORDING, SessionStatus.FAILED): "session.failed",
}


class SessionStateMachine:
    """Centralised session state transitions with guard enforcement."""

    def validate_transition(self, from_status: SessionStatus, to_status: SessionStatus) -> bool:
        """Return True if the transition is valid; raise InvalidTransitionError otherwise."""
        if (from_status, to_status) not in TRANSITIONS:
            msg = f"Illegal session transition: {from_status} -> {to_status}"
            raise InvalidTransitionError(msg)
        return True

    async def transition(
        self,
        session: Session,
        to_status: SessionStatus,
        db: AsyncSession,
        reason: str | None = None,
        stage: str | None = None,
    ) -> Session:
        """Validate and apply a transition, updating failure/retry bookkeeping.

        Uses `SELECT ... FOR UPDATE` to serialise concurrent transitions on
        the same session row (T23.5); a losing concurrent transaction sees a
        stale `session.status` after acquiring the lock and must re-validate.
        """
        locked = await db.get(Session, session.id, with_for_update=True)
        if locked is None:
            msg = f"Session {session.id} not found"
            raise InvalidTransitionError(msg)

        from_status = SessionStatus(locked.status)
        self.validate_transition(from_status, to_status)

        locked.status = to_status
        if to_status == SessionStatus.FAILED:
            locked.failure_reason = reason
            locked.failure_stage = stage
            locked.notes_ready = False
        elif from_status == SessionStatus.FAILED and to_status == SessionStatus.PROCESSING:
            locked.retry_count += 1
            locked.last_retry_at = datetime.now(UTC)
            locked.failure_reason = None
            locked.failure_stage = None
        elif to_status in (SessionStatus.COMPLETE,):
            locked.failure_reason = None
            locked.failure_stage = None

        await db.flush()

        event_name = _EVENT_NAMES.get((from_status, to_status), "session.transition")
        logger.info(
            "%s session_id=%s from=%s to=%s reason=%s",
            event_name,
            locked.id,
            from_status,
            to_status,
            reason,
        )
        return locked
