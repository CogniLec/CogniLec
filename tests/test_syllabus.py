"""S11 - DB-3: Syllabus Instance & FDW Link tests (T11.1-T11.5)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.models.subject import Subject
from src.db.models.user import User
from src.db.repositories.syllabus_repo import SyllabusFdwReader, SyllabusRepository


async def _create_user_and_subject(session: AsyncSession) -> Subject:
    user = User(
        email=f"test-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="hashed",
        is_active=True,
    )
    session.add(user)
    await session.flush()

    subject = Subject(user_id=user.id, name=f"Subject {uuid.uuid4().hex[:6]}")
    session.add(subject)
    await session.flush()
    return subject


@pytest.mark.integration
class TestSyllabusHierarchy:
    """T11.1 - hierarchy inserts and reads correctly (direct connection)."""

    async def test_hierarchy(self, syllabus_session: AsyncSession) -> None:
        repo = SyllabusRepository(syllabus_session)
        subject_id = uuid.uuid4()

        parent = await repo.create_item(
            subject_id,
            {
                "parent_id": None,
                "ordinal": 1,
                "title": "Unit 1",
                "description": None,
                "source": "manual",
                "source_session_id": None,
            },
        )
        parent_id = parent["id"]

        child = await repo.create_item(
            subject_id,
            {
                "parent_id": parent_id,
                "ordinal": 1,
                "title": "Unit 1.1",
                "description": None,
                "source": "manual",
                "source_session_id": None,
            },
        )
        child_id = child["id"]

        tree = await repo.get_tree(subject_id)
        assert len(tree) == 2

        fetched_parent = await repo.get_item(parent_id)
        fetched_child = await repo.get_item(child_id)
        assert fetched_parent is not None
        assert fetched_child is not None
        assert fetched_parent["parent_id"] is None
        assert fetched_child["parent_id"] == parent_id
        assert fetched_child["title"] == "Unit 1.1"

    async def test_delete_item(self, syllabus_session: AsyncSession) -> None:
        repo = SyllabusRepository(syllabus_session)
        subject_id = uuid.uuid4()
        item = await repo.create_item(
            subject_id,
            {
                "parent_id": None,
                "ordinal": 1,
                "title": "Doomed",
                "description": None,
                "source": "manual",
                "source_session_id": None,
            },
        )
        assert await repo.delete_item(item["id"]) is True
        assert await repo.get_item(item["id"]) is None
        assert await repo.delete_item(uuid.uuid4()) is False

    async def test_update_coverage(self, syllabus_session: AsyncSession) -> None:
        repo = SyllabusRepository(syllabus_session)
        subject_id = uuid.uuid4()
        item = await repo.create_item(
            subject_id,
            {
                "parent_id": None,
                "ordinal": 1,
                "title": "Covered later",
                "description": None,
                "source": "manual",
                "source_session_id": None,
            },
        )
        topic_id = uuid.uuid4()
        updated = await repo.update_coverage(item["id"], "covered", [topic_id])
        assert updated is not None
        assert updated["coverage_status"] == "covered"
        assert updated["covered_by"] == [topic_id]


@pytest.mark.integration
class TestSyllabusFdw:
    """T11.2/T11.3 - FDW read-through from PG-MAIN."""

    async def test_fdw_query(
        self, db_session: AsyncSession, syllabus_session: AsyncSession
    ) -> None:
        """T11.2: FDW query from PG-MAIN returns rows inserted via PG-SYLLABUS."""
        subject_id = uuid.uuid4()
        syllabus_repo = SyllabusRepository(syllabus_session)
        await syllabus_repo.create_item(
            subject_id,
            {
                "parent_id": None,
                "ordinal": 1,
                "title": "FDW visible item",
                "description": None,
                "source": "manual",
                "source_session_id": None,
            },
        )
        # FDW reads on PG-MAIN use a separate connection to PG-SYLLABUS, so
        # the insert must be committed before it's visible there.
        await syllabus_session.commit()

        reader = SyllabusFdwReader(db_session)
        rows = await reader.get_items_for_subject(subject_id)
        assert len(rows) == 1
        assert rows[0]["title"] == "FDW visible item"

    async def test_fdw_join(self, db_session: AsyncSession, syllabus_session: AsyncSession) -> None:
        """T11.3: join between local subjects and foreign syllabus_items."""
        subject = await _create_user_and_subject(db_session)

        syllabus_repo = SyllabusRepository(syllabus_session)
        await syllabus_repo.create_item(
            subject.id,
            {
                "parent_id": None,
                "ordinal": 1,
                "title": "Joined item",
                "description": None,
                "source": "manual",
                "source_session_id": None,
            },
        )
        await syllabus_session.commit()

        reader = SyllabusFdwReader(db_session)
        rows = await reader.get_subject_syllabus(subject.id)
        assert len(rows) == 1
        assert rows[0]["subject_id"] == subject.id
        assert rows[0]["subject_name"] == subject.name
        assert rows[0]["title"] == "Joined item"


@pytest.mark.integration
class TestSyllabusFdwFailure:
    """T11.4 - PG-SYLLABUS unavailable: FDW query fails cleanly, not a hang."""

    async def test_fdw_failure(self, db_session: AsyncSession) -> None:
        # Point a throwaway FDW server at an unreachable host, isolated from
        # the real syllabus_server so this doesn't disrupt other tests.
        await db_session.execute(text("CREATE EXTENSION IF NOT EXISTS postgres_fdw"))
        await db_session.execute(
            text(
                "CREATE SERVER IF NOT EXISTS broken_syllabus_server "
                "FOREIGN DATA WRAPPER postgres_fdw "
                "OPTIONS (host 'nonexistent-host-for-t11-4', port '5432', dbname 'lis_syllabus')"
            )
        )
        await db_session.execute(
            text("DROP USER MAPPING IF EXISTS FOR lis SERVER broken_syllabus_server")
        )
        await db_session.execute(
            text(
                "CREATE USER MAPPING FOR lis SERVER broken_syllabus_server "
                "OPTIONS (user 'lis_fdw_reader', password 'lis_fdw_reader_dev')"
            )
        )
        await db_session.execute(
            text(
                "CREATE FOREIGN TABLE broken_syllabus_items (id uuid) "
                "SERVER broken_syllabus_server OPTIONS (schema_name 'public', "
                "table_name 'syllabus_items')"
            )
        )
        await db_session.commit()

        with pytest.raises(DBAPIError):
            await db_session.execute(text("SELECT * FROM broken_syllabus_items"))
        await db_session.rollback()


@pytest.mark.integration
class TestSyllabusFdwReadOnly:
    """T11.5 - FDW user mapping has read-only rights from PG-MAIN's side."""

    async def test_fdw_readonly(self, db_session: AsyncSession) -> None:
        with pytest.raises(DBAPIError, match="permission denied"):
            await db_session.execute(
                text(
                    "INSERT INTO syllabus_items (id, subject_id, ordinal, title) "
                    "VALUES (gen_random_uuid(), gen_random_uuid(), 1, 'blocked')"
                )
            )
        await db_session.rollback()

        with pytest.raises(DBAPIError, match="permission denied"):
            await db_session.execute(text("DELETE FROM syllabus_items WHERE title = 'blocked'"))
        await db_session.rollback()
