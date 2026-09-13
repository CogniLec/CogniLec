"""Tests for S50 T50.4 — write-authority enforcement on DB-3.

Two layers are exercised here:

1. Application-level `DB3WriteGuard` (the enforced gate in this
   environment - see docker/postgres/migrations/syllabus/002_syllabus_items_extend.sql
   and docs/gaps.md gap #9 for why the DB-role REVOKE from "lis" was not
   applied to the shared "lis" role that other blocks' fixtures depend on).
2. The `a6_writer` DB role actually exists with INSERT/UPDATE/DELETE grants
   on syllabus_items, confirming the DB-level half of FR-3.8 is at least
   additively present.
"""

from __future__ import annotations

import uuid

import pytest
from config.schemas.a6_syllabus import ExtractedSyllabusItem, ItemType
from sqlalchemy import text
from src.db.repositories.syllabus_repo import SyllabusRepository
from src.db.write_guard import DB3WriteGuard


async def test_only_a6_writes_db3(syllabus_session) -> None:
    """Outside DB3WriteGuard.a6_write_context, any write attempt is rejected."""
    repo = SyllabusRepository(syllabus_session)
    item = ExtractedSyllabusItem(title="Module 1", item_type=ItemType.MODULE, ordinal=0)

    with pytest.raises(PermissionError):
        await repo.bulk_create_items(uuid.uuid4(), [item])

    # Inside the guard, the write succeeds.
    with DB3WriteGuard.a6_write_context():
        created = await repo.bulk_create_items(uuid.uuid4(), [item])
    assert len(created) == 1


async def test_guard_context_is_scoped(syllabus_session) -> None:
    """The write-authority context does not leak across calls."""
    repo = SyllabusRepository(syllabus_session)
    item = ExtractedSyllabusItem(title="Module 1", item_type=ItemType.MODULE, ordinal=0)

    with DB3WriteGuard.a6_write_context():
        await repo.bulk_create_items(uuid.uuid4(), [item])

    with pytest.raises(PermissionError):
        await repo.bulk_create_items(uuid.uuid4(), [item])


async def test_a6_writer_role_exists_with_grants(syllabus_session) -> None:
    """DB-level half of FR-3.8: a6_writer role exists with write grants."""
    role_exists = (
        await syllabus_session.execute(
            text("SELECT count(*) FROM pg_roles WHERE rolname = 'a6_writer'")
        )
    ).scalar_one()
    assert role_exists == 1

    grants = (
        (
            await syllabus_session.execute(
                text(
                    "SELECT privilege_type FROM information_schema.role_table_grants "
                    "WHERE table_name = 'syllabus_items' AND grantee = 'a6_writer'"
                )
            )
        )
        .scalars()
        .all()
    )
    assert {"INSERT", "UPDATE", "DELETE"}.issubset(set(grants))
