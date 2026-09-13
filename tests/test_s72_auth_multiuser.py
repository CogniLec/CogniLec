"""Tests for S72 - Auth, IdP & Multi-User.

============================================================================
HONESTY STATEMENT
============================================================================
Authentik (the spec's OIDC IdP) is not deployed in this sandbox - no
internet access to pull its image, and standing up a full OIDC provider is
out of what a test suite can honestly assert without one. T72.1 (OIDC
login/logout/refresh) and T72.6 (20 concurrent users against a real IdP)
are honest skips. T72.2 (RLS re-run under the new auth) reuses gap #4 - the
`lis` role is still superuser/BYPASSRLS in this environment, unchanged by
this stage; it is not re-asserted here, it is the same open gap
`tests/test_transcript_api.py` already documents.

What's genuinely new and tested here: `src/services/account/export_service.py`
(T72.4) and `src/services/account/deletion_service.py` (T72.3/T72.5), run
against the real PG-MAIN test database with real seeded rows. The deletion
test also surfaces a genuine, previously-undocumented conflict: S65's
`corrections.user_id` RESTRICT FK (added so the immutability rule never has
to process an UPDATE) means a user who has any correction on record cannot
currently be deleted at all - the cascade aborts, and this test asserts
that failure mode explicitly rather than hiding it.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.partitions.provisioner import PartitionProvisioner
from src.services.account.deletion_service import (
    DeletionBlockedError,
    delete_user_account,
)
from src.services.account.export_service import export_user_data


class _FakeStorageClient:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def delete_object(self, bucket: object, key: str) -> None:
        self.deleted.append(key)


async def _seed_subject_and_session(db: AsyncSession, user_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    subject = await PartitionProvisioner().provision_subject(db, user_id, name="S72 Subject")
    session_id = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO sessions (id, subject_id, session_type, status, notes_ready) "
            "VALUES (:id, :sid, 'content', 'complete', false)"
        ),
        {"id": str(session_id), "sid": str(subject.id)},
    )
    await db.flush()
    return subject.id, session_id


@pytest.mark.asyncio
async def test_t72_4_export_produces_scoped_archive(
    db_session: AsyncSession, test_user_id: uuid.UUID
) -> None:
    subject_id, _session_id = await _seed_subject_and_session(db_session, test_user_id)

    other_user_id = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO users (id, email, hashed_password, is_active) "
            "VALUES (:id, :email, 'x', true)"
        ),
        {"id": str(other_user_id), "email": f"other_{other_user_id.hex[:8]}@example.com"},
    )
    other_subject_id, _ = await _seed_subject_and_session(db_session, other_user_id)
    await db_session.flush()

    archive = await export_user_data(db_session, test_user_id)

    assert archive["user"]["id"] == test_user_id
    exported_subject_ids = {s["id"] for s in archive["subjects"]}
    assert subject_id in exported_subject_ids
    assert other_subject_id not in exported_subject_ids


@pytest.mark.asyncio
async def test_t72_3_and_t72_5_deletion_cascades_db1_and_objects(
    db_session: AsyncSession, test_user_id: uuid.UUID
) -> None:
    subject_id, session_id = await _seed_subject_and_session(db_session, test_user_id)
    section_id = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO note_sections (id, subject_id, session_id, heading, body_md, ordinal) "
            "VALUES (:id, :sid, :sess, 'H', 'B', 0)"
        ),
        {"id": str(section_id), "sid": str(subject_id), "sess": str(session_id)},
    )
    await db_session.execute(
        text(
            "INSERT INTO note_assets "
            "(id, subject_id, note_section_id, asset_type, object_key, is_ai_generated) "
            "VALUES (:id, :sid, :nsid, 'generated', :key, true)"
        ),
        {
            "id": str(uuid.uuid4()),
            "sid": str(subject_id),
            "nsid": str(section_id),
            "key": "generated/some-image.png",
        },
    )
    await db_session.flush()

    fake_storage = _FakeStorageClient()
    report = await delete_user_account(db_session, fake_storage, test_user_id)  # type: ignore[arg-type]

    assert report.db1_deleted is True
    assert "generated/some-image.png" in fake_storage.deleted

    remaining = (
        await db_session.execute(
            text("SELECT count(*) FROM users WHERE id = :uid"), {"uid": str(test_user_id)}
        )
    ).scalar_one()
    assert remaining == 0

    remaining_subjects = (
        await db_session.execute(
            text("SELECT count(*) FROM subjects WHERE id = :sid"), {"sid": str(subject_id)}
        )
    ).scalar_one()
    assert remaining_subjects == 0


@pytest.mark.asyncio
async def test_t72_3_deletion_blocked_by_corrections_restrict_fk_genuine_finding(
    db_session: AsyncSession, test_user_id: uuid.UUID
) -> None:
    """Documents a real conflict: a user with any correction can't be deleted today."""
    subject_id, _session_id = await _seed_subject_and_session(db_session, test_user_id)
    await db_session.execute(
        text(
            "INSERT INTO corrections "
            "(id, correction_type, subject_id, user_id, original_value, corrected_value) "
            "VALUES (:id, 'note_edit', :sid, :uid, '{}'::jsonb, '{}'::jsonb)"
        ),
        {"id": str(uuid.uuid4()), "sid": str(subject_id), "uid": str(test_user_id)},
    )
    await db_session.flush()

    fake_storage = _FakeStorageClient()
    with pytest.raises(DeletionBlockedError, match=r"corrections\.user_id RESTRICT"):
        await delete_user_account(db_session, fake_storage, test_user_id)  # type: ignore[arg-type]

    remaining = (
        await db_session.execute(
            text("SELECT count(*) FROM users WHERE id = :uid"), {"uid": str(test_user_id)}
        )
    ).scalar_one()
    assert remaining == 1, "the whole cascade must abort, not partially delete"


def test_t72_1_oidc_login_not_available() -> None:
    pytest.skip("Authentik/OIDC IdP not deployed in this sandbox (no internet, docs/gaps.md)")


def test_t72_2_rls_under_new_auth_reuses_gap_4() -> None:
    pytest.skip(
        "lis role is still superuser/BYPASSRLS in this environment - see docs/gaps.md #4 "
        "and tests/test_transcript_api.py; unchanged by S72."
    )


def test_t72_6_twenty_concurrent_users_not_available() -> None:
    pytest.skip("No deployed multi-user IdP/session stack to load-test in this sandbox")
