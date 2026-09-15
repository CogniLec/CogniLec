"""Shared per-request ownership checks.

Found by live audit (docs/gaps.md): most routes either had no auth
dependency at all, or (like study.py's original `_get_owned_subject_id`)
checked only that a row existed, never that it belonged to the caller --
relying entirely on RLS, which is bypassed in this environment (gap #4).
These helpers make ownership an explicit, real check independent of RLS.

Plain functions, not their own FastAPI dependencies: callers pass the
`db`/`current_user` they already resolved via their own `Depends`, so a
route only opens one DB session per request rather than one per
dependency callable.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.session import Session
from src.db.models.subject import Subject
from src.db.repositories.session_repo import SessionRepository
from src.db.repositories.subject_repo import SubjectRepository


async def require_owned_subject(
    subject_id: uuid.UUID,
    db: AsyncSession,
    current_user: dict[str, object],
) -> Subject:
    """Fetch a subject, 404ing if it doesn't exist OR belongs to someone else.

    Same response (404, not 403) either way, so a caller can't distinguish
    "not yours" from "doesn't exist" (no existence leak).
    """
    subject = await SubjectRepository(db).get(subject_id)
    if subject is None or str(subject.user_id) != str(current_user["id"]):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subject not found")
    return subject


async def require_owned_session(
    session_id: uuid.UUID,
    db: AsyncSession,
    current_user: dict[str, object],
) -> Session:
    """Fetch a session, 404ing unless its subject belongs to the caller."""
    session_obj = await SessionRepository(db).get(session_id)
    if session_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    subject = await SubjectRepository(db).get(session_obj.subject_id)
    if subject is None or str(subject.user_id) != str(current_user["id"]):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return session_obj
