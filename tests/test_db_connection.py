"""Test database connectivity and extensions."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class TestDBConnection:
    async def test_pgvector_extension(self, db_session: AsyncSession):
        result = await db_session.execute(
            text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
        )
        row = result.fetchone()
        assert row is not None

    async def test_uuid_extension(self, db_session: AsyncSession):
        result = await db_session.execute(
            text("SELECT extname FROM pg_extension WHERE extname = 'uuid-ossp'")
        )
        row = result.fetchone()
        assert row is not None

    async def test_citext_extension(self, db_session: AsyncSession):
        result = await db_session.execute(
            text("SELECT extname FROM pg_extension WHERE extname = 'citext'")
        )
        row = result.fetchone()
        assert row is not None

    async def test_gen_random_uuid(self, db_session: AsyncSession):
        result = await db_session.execute(text("SELECT gen_random_uuid()"))
        row = result.fetchone()
        assert row is not None
