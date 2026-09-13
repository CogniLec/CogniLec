"""Tests for S10 — Notes, Provenance & Assets (NoteRepository).

This stage previously had a real DB schema (migration c58ea6212bc5) with the
correct NFR-S7 licence constraint, but the NoteRepository above it had never
been exercised by any test and had no API layer. This file verifies the
repository actually works against a real database and exercises the T10.1-
T10.5 assertions from the S10 spec.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.models.session import Session
from src.db.models.user import User
from src.db.partitions.provisioner import PartitionProvisioner
from src.db.repositories.note_repo import NoteRepository


async def _make_subject_and_session(db_session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    user = User(
        email=f"notes-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="hashed",
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()

    provisioner = PartitionProvisioner()
    subject = await provisioner.provision_subject(db_session, user.id, name="Notes Test Subject")
    subject_id = subject.id

    session_obj = Session(subject_id=subject_id, session_type="content")
    db_session.add(session_obj)
    await db_session.flush()
    session_id = session_obj.id

    await db_session.commit()
    return subject_id, session_id


@pytest.mark.integration
class TestNoteSectionAndProvenance:
    """T10.1 — note section with provenance links inserts and reads back."""

    async def test_create_section_and_provenance_round_trip(self, db_session: AsyncSession) -> None:
        subject_id, session_id = await _make_subject_and_session(db_session)
        repo = NoteRepository(db_session)

        section = await repo.create_section(
            subject_id,
            {
                "topic_id": None,
                "session_id": session_id,
                "heading": "Intro to Thermodynamics",
                "body_md": "# Heat and work\n...",
                "depth": 0,
                "ordinal": 0,
                "model_version": "a2-v1",
            },
        )
        assert "id" in section
        section_id = section["id"]
        await db_session.commit()

        utterance_ids = [uuid.uuid4(), uuid.uuid4()]
        # note_provenance.utterance_id has no FK constraint in the migration,
        # so this is a structural round-trip check, not a referential one.
        count = await repo.create_provenance(subject_id, section_id, utterance_ids)
        assert count == 2
        await db_session.commit()

        sections = await repo.get_sections_by_session(subject_id, session_id)
        assert len(sections) == 1


@pytest.mark.integration
class TestNoteAssetLicenceConstraint:
    """T10.2 — web_image asset without licence is rejected by constraint (NFR-S7)."""

    async def test_web_image_without_licence_rejected(self, db_session: AsyncSession) -> None:
        subject_id, session_id = await _make_subject_and_session(db_session)
        repo = NoteRepository(db_session)
        section = await repo.create_section(
            subject_id,
            {
                "topic_id": None,
                "session_id": session_id,
                "heading": "Diagram section",
                "body_md": "body",
                "depth": 0,
                "ordinal": 0,
                "model_version": "a2-v1",
            },
        )
        await db_session.flush()

        with pytest.raises(IntegrityError):
            await repo.create_asset(
                subject_id,
                {
                    "note_section_id": section["id"],
                    "asset_type": "web_image",
                    "object_key": "img.png",
                    "source_url": None,
                    "licence": None,
                    "match_score": 0.8,
                    "is_ai_generated": False,
                    "ocr_text": None,
                    "ocr_confidence": None,
                },
            )
        await db_session.rollback()

    async def test_web_image_with_licence_accepted(self, db_session: AsyncSession) -> None:
        subject_id, session_id = await _make_subject_and_session(db_session)
        repo = NoteRepository(db_session)
        section = await repo.create_section(
            subject_id,
            {
                "topic_id": None,
                "session_id": session_id,
                "heading": "Diagram section",
                "body_md": "body",
                "depth": 0,
                "ordinal": 0,
                "model_version": "a2-v1",
            },
        )
        await db_session.flush()

        asset = await repo.create_asset(
            subject_id,
            {
                "note_section_id": section["id"],
                "asset_type": "web_image",
                "object_key": "img.png",
                "source_url": "https://commons.wikimedia.org/x.png",
                "licence": "CC-BY-4.0",
                "match_score": 0.8,
                "is_ai_generated": False,
                "ocr_text": None,
                "ocr_confidence": None,
            },
        )
        assert "id" in asset
        await db_session.commit()

        assets = await repo.get_assets(section["id"])
        assert len(assets) == 1


@pytest.mark.integration
class TestNoteSectionCascade:
    """T10.3 — deleting a note section cascades to provenance and assets."""

    async def test_delete_section_cascades(self, db_session: AsyncSession) -> None:
        subject_id, session_id = await _make_subject_and_session(db_session)
        repo = NoteRepository(db_session)
        section = await repo.create_section(
            subject_id,
            {
                "topic_id": None,
                "session_id": session_id,
                "heading": "H",
                "body_md": "b",
                "depth": 0,
                "ordinal": 0,
                "model_version": "a2-v1",
            },
        )
        section_id = section["id"]
        await repo.create_provenance(subject_id, section_id, [uuid.uuid4()])
        await repo.create_asset(
            subject_id,
            {
                "note_section_id": section_id,
                "asset_type": "diagram",
                "object_key": "d.svg",
                "source_url": None,
                "licence": None,
                "match_score": None,
                "is_ai_generated": True,
                "ocr_text": None,
                "ocr_confidence": None,
            },
        )
        await db_session.commit()

        await db_session.execute(
            text("DELETE FROM note_sections WHERE subject_id = :sid AND id = :id"),
            {"sid": subject_id, "id": section_id},
        )
        await db_session.commit()

        remaining_provenance = await db_session.execute(
            text("SELECT count(*) FROM note_provenance WHERE note_section_id = :id"),
            {"id": section_id},
        )
        remaining_assets = await db_session.execute(
            text("SELECT count(*) FROM note_assets WHERE note_section_id = :id"),
            {"id": section_id},
        )
        assert remaining_provenance.scalar_one() == 0
        assert remaining_assets.scalar_one() == 0


@pytest.mark.integration
class TestNoteAssetTypeConstraint:
    """T10.5 — asset_type check constraint rejects unknown types."""

    async def test_unknown_asset_type_rejected(self, db_session: AsyncSession) -> None:
        subject_id, session_id = await _make_subject_and_session(db_session)
        repo = NoteRepository(db_session)
        section = await repo.create_section(
            subject_id,
            {
                "topic_id": None,
                "session_id": session_id,
                "heading": "H",
                "body_md": "b",
                "depth": 0,
                "ordinal": 0,
                "model_version": "a2-v1",
            },
        )
        await db_session.flush()

        with pytest.raises(IntegrityError):
            await repo.create_asset(
                subject_id,
                {
                    "note_section_id": section["id"],
                    "asset_type": "not_a_real_type",
                    "object_key": "x",
                    "source_url": None,
                    "licence": None,
                    "match_score": None,
                    "is_ai_generated": False,
                    "ocr_text": None,
                    "ocr_confidence": None,
                },
            )
        await db_session.rollback()

    async def test_known_asset_type_accepted(self, db_session: AsyncSession) -> None:
        subject_id, session_id = await _make_subject_and_session(db_session)
        repo = NoteRepository(db_session)
        section = await repo.create_section(
            subject_id,
            {
                "topic_id": None,
                "session_id": session_id,
                "heading": "H",
                "body_md": "b",
                "depth": 0,
                "ordinal": 0,
                "model_version": "a2-v1",
            },
        )
        await db_session.flush()

        asset = await repo.create_asset(
            subject_id,
            {
                "note_section_id": section["id"],
                "asset_type": "diagram",
                "object_key": "x",
                "source_url": None,
                "licence": None,
                "match_score": None,
                "is_ai_generated": True,
                "ocr_text": None,
                "ocr_confidence": None,
            },
        )
        assert "id" in asset
        await db_session.commit()
