"""S72 — full data export of a single user's own data (T72.4, NFR-S6).

Authentik/OIDC (the spec's IdP) is not deployed in this sandbox - see
`docs/gaps.md` - so this module does not touch authentication at all. It
covers the other, independently-testable half of S72: given a `user_id`,
produce a complete, JSON-serialisable archive of every row that user owns
in DB-1 (PG-MAIN), scoped strictly by ownership so a bug here cannot leak
another user's data.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def export_user_data(db_session: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    """Return every row this user owns, scoped by the subjects->sessions ownership chain."""
    user_row = (
        (
            await db_session.execute(
                text("SELECT id, email, created_at FROM users WHERE id = :uid"),
                {"uid": str(user_id)},
            )
        )
        .mappings()
        .first()
    )
    if user_row is None:
        msg = f"no such user: {user_id}"
        raise ValueError(msg)

    subjects = (
        (
            await db_session.execute(
                text("SELECT * FROM subjects WHERE user_id = :uid"), {"uid": str(user_id)}
            )
        )
        .mappings()
        .all()
    )
    subject_ids = [row["id"] for row in subjects]

    sessions: list[Any] = []
    corrections: list[Any] = []
    if subject_ids:
        sessions = list(
            (
                await db_session.execute(
                    text("SELECT * FROM sessions WHERE subject_id = ANY(:sids)"),
                    {"sids": subject_ids},
                )
            )
            .mappings()
            .all()
        )
        corrections = list(
            (
                await db_session.execute(
                    text("SELECT * FROM corrections WHERE subject_id = ANY(:sids)"),
                    {"sids": subject_ids},
                )
            )
            .mappings()
            .all()
        )

    session_ids = [row["id"] for row in sessions]
    note_sections: list[Any] = []  # populated below when session_ids is non-empty
    if session_ids:
        note_sections = list(
            (
                await db_session.execute(
                    text("SELECT * FROM note_sections WHERE session_id = ANY(:sids)"),
                    {"sids": session_ids},
                )
            )
            .mappings()
            .all()
        )

    return {
        "user": dict(user_row),
        "subjects": [dict(r) for r in subjects],
        "sessions": [dict(r) for r in sessions],
        "note_sections": [dict(r) for r in note_sections],
        "corrections": [dict(r) for r in corrections],
    }
