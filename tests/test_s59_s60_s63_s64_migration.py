"""DB-level checks for the Block 11 migration (b3d6e8f1a4c7).

Verifies the new columns/tables/constraints this block's persistence
layer depends on actually exist and enforce what they claim to, against
the real pg-main database (via the shared `db_session` fixture, which
runs `alembic upgrade head` before yielding).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from src.db.partitions.provisioner import PartitionProvisioner
from src.db.repositories.generation_cache_repo import GenerationCacheRepository
from src.db.repositories.upload_repo import UploadRepository
from src.services.uploads.models import FileType, UploadStatus


async def _make_subject_and_section(db_session, user_id):
    subject = await PartitionProvisioner().provision_subject(db_session, user_id, name="Bio")
    subject_id = subject.id
    section_id = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO note_sections (subject_id, id, heading, body_md, ordinal) "
            "VALUES (:sid, :id, 'Heading', 'Body', 0)"
        ),
        {"sid": subject_id, "id": section_id},
    )
    await db_session.flush()
    return subject_id, section_id


@pytest.mark.asyncio
async def test_upload_tracking_columns_exist_and_persist(db_session, test_user_id):
    subject_id, _section_id = await _make_subject_and_section(db_session, test_user_id)
    session_id = uuid.uuid4()

    repo = UploadRepository(db_session)
    record = await repo.create_upload(
        session_id=session_id,
        subject_id=subject_id,
        file_type=FileType.IMAGE,
        original_filename="board.jpg",
        stored_bytes=b"stub",
        status=UploadStatus.UNIQUE,
        exif_stripped=True,
        phash="abcd1234",
        merged_asset_id=None,
    )
    assert record["exif_stripped"] is True
    assert record["phash"] == "abcd1234"

    row = (
        await db_session.execute(
            text(
                "SELECT upload_id, original_filename, exif_stripped, phash "
                "FROM note_assets WHERE id = :id"
            ),
            {"id": record["id"]},
        )
    ).fetchone()
    assert row is not None
    assert row.original_filename == "board.jpg"
    assert row.exif_stripped is True
    assert row.phash == "abcd1234"


@pytest.mark.asyncio
async def test_image_generation_cache_unique_constraint(db_session, test_user_id):
    subject_id = uuid.uuid4()
    await db_session.execute(
        text("INSERT INTO subjects (id, user_id, name) VALUES (:id, :uid, 'Bio')"),
        {"id": subject_id, "uid": test_user_id},
    )
    await db_session.flush()

    repo = GenerationCacheRepository(db_session)
    image_id = uuid.uuid4()
    await repo.put(subject_id, "Anatomy of the human heart", image_id)

    fetched = await repo.get(subject_id, "  ANATOMY of the Human Heart  ")
    assert fetched == image_id

    # Second put with the same (subject, concept) is a no-op (ON CONFLICT
    # DO NOTHING), not a duplicate row / integrity error.
    other_image_id = uuid.uuid4()
    await repo.put(subject_id, "Anatomy of the human heart", other_image_id)
    assert await repo.get(subject_id, "Anatomy of the human heart") == image_id


@pytest.mark.asyncio
async def test_note_asset_attachments_check_constraint_rejects_bad_type(db_session, test_user_id):
    subject_id, section_id = await _make_subject_and_section(db_session, test_user_id)
    with pytest.raises(IntegrityError):
        await db_session.execute(
            text(
                "INSERT INTO note_asset_attachments "
                "(note_section_id, subject_id, asset_type, asset_id) "
                "VALUES (:sec, :subj, 'not_a_real_type', :aid)"
            ),
            {"sec": section_id, "subj": subject_id, "aid": uuid.uuid4()},
        )
        await db_session.flush()


@pytest.mark.asyncio
async def test_note_asset_attachments_accepts_valid_type(db_session, test_user_id):
    subject_id, section_id = await _make_subject_and_section(db_session, test_user_id)
    asset_id = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO note_asset_attachments "
            "(note_section_id, subject_id, asset_type, asset_id, ordinal) "
            "VALUES (:sec, :subj, 'text_diagram', :aid, 0)"
        ),
        {"sec": section_id, "subj": subject_id, "aid": asset_id},
    )
    await db_session.flush()
    row = (
        await db_session.execute(
            text("SELECT asset_type FROM note_asset_attachments WHERE asset_id = :aid"),
            {"aid": asset_id},
        )
    ).fetchone()
    assert row.asset_type == "text_diagram"
