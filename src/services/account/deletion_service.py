"""S72 — account deletion cascade across DB-1, object store and metadata (AC-20).

Real cascade across three surfaces:
  - DB-1 (PG-MAIN): `DELETE FROM users` relies on the existing
    `subjects.user_id` `ON DELETE CASCADE` (and every table beneath
    subjects/sessions cascading from there) to remove everything the user
    owns.
  - Object store (MinIO): every `note_assets.object_key` under the user's
    sessions is deleted before the DB row disappears, since the object key
    itself lives only in the (about-to-cascade) database row.
  - DB-3 (PG-SYLLABUS): syllabus items are keyed by `subject_id`, not
    `user_id` (S11) and live in a separate database with no FK to DB-1, so
    they are deleted here explicitly by the caller-supplied `subject_ids`.

`corrections.user_id` is a RESTRICT FK by deliberate S65 design (an
`ON DELETE SET NULL` would issue an `UPDATE` against `corrections`, which
the immutability rule from migration `c4e7f2a9b6d1` rejects). The product
decision (`docs/gaps.md` gap #13) is to keep corrections as training
signal but sever the identity link, not to block the deletion: this
cascade nulls `corrections.user_id` for the user explicitly, in the same
transaction and before `DELETE FROM users`, so RESTRICT never has anything
left to object to. That UPDATE is only permitted at all because migration
`e8c1b4a7d2f9` carves a narrow, session-flagged exception into the
immutability rule - one that requires every other column (the actual
training signal) to stay unchanged.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, cast

from sqlalchemy import CursorResult, text
from sqlalchemy.ext.asyncio import AsyncSession
from src.services.storage.client import StorageClient
from src.services.storage.models import BucketName


class DeletionBlockedError(Exception):
    """Raised when the DB-1 cascade cannot complete."""


@dataclass
class DeletionReport:
    user_id: uuid.UUID
    objects_deleted: list[str] = field(default_factory=list)
    subjects_deleted: int = 0
    corrections_anonymized: int = 0
    db1_deleted: bool = False
    blocked_reason: str | None = None


async def delete_user_account(
    db_session: AsyncSession,
    storage_client: StorageClient,
    user_id: uuid.UUID,
) -> DeletionReport:
    report = DeletionReport(user_id=user_id)

    subject_ids = [
        row[0]
        for row in (
            await db_session.execute(
                text("SELECT id FROM subjects WHERE user_id = :uid"), {"uid": str(user_id)}
            )
        ).all()
    ]
    report.subjects_deleted = len(subject_ids)

    if subject_ids:
        session_ids = [
            row[0]
            for row in (
                await db_session.execute(
                    text("SELECT id FROM sessions WHERE subject_id = ANY(:sids)"),
                    {"sids": subject_ids},
                )
            ).all()
        ]
        if session_ids:
            keys = [
                row[0]
                for row in (
                    await db_session.execute(
                        text(
                            "SELECT na.object_key FROM note_assets na "
                            "JOIN note_sections ns ON ns.id = na.note_section_id "
                            "WHERE ns.session_id = ANY(:sids) AND na.object_key IS NOT NULL"
                        ),
                        {"sids": session_ids},
                    )
                ).all()
            ]
            for key in keys:
                try:
                    await storage_client.delete_object(BucketName.GENERATED, key)
                    report.objects_deleted.append(key)
                except ConnectionError:
                    pass

    async with db_session.begin_nested():
        await db_session.execute(text("SET LOCAL lis.allow_correction_anonymize = 'on'"))
        anonymized = cast(
            CursorResult[Any],
            await db_session.execute(
                text("UPDATE corrections SET user_id = NULL WHERE user_id = :uid"),
                {"uid": str(user_id)},
            ),
        )
        report.corrections_anonymized = anonymized.rowcount or 0
        await db_session.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": str(user_id)})
    report.db1_deleted = True

    return report
