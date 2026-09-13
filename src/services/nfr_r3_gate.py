"""NFR-R3 durability gate: downstream flows must not start before a
session's transcript has been durably committed (S19 spec section 5).
"""

from __future__ import annotations

from uuid import UUID

from src.db.models.session import SessionStatus
from src.db.repositories.session_repo import SessionRepository


class NFR_R3_Gate:  # noqa: N801 - name fixed by S19 spec section 5
    """Asserts a session is `transcribed` before a downstream flow may start."""

    def __init__(self, session_repo: SessionRepository) -> None:
        self.session_repo = session_repo

    async def assert_transcribed(self, session_id: UUID) -> bool:
        """Assert session is in 'transcribed' status.

        Raises ValueError if not.
        NFR-R3: Transcript committed before downstream starts.
        """
        session = await self.session_repo.get_or_raise(session_id)
        if session.status != SessionStatus.TRANSCRIBED:
            msg = (
                f"NFR-R3 violated: session {session_id} "
                f"status is '{session.status}', expected 'transcribed'"
            )
            raise ValueError(msg)
        return True
