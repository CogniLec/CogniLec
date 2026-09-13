"""Test fixtures for integration tests."""

from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# S11: syllabus_items DDL, applied out-of-band since alembic only targets PG-MAIN.
SYLLABUS_SCHEMA_SQL = (
    Path(__file__).resolve().parents[1]
    / "docker"
    / "postgres"
    / "migrations"
    / "syllabus"
    / "001_syllabus_items.sql"
).read_text()

# Connect directly to PostgreSQL, bypassing PgBouncer
DATABASE_URL = "postgresql+asyncpg://lis:lis_dev@localhost:5434/lis_main"
SYLLABUS_DATABASE_URL = "postgresql+asyncpg://lis:lis_dev@localhost:5435/lis_syllabus"


@pytest.fixture(scope="function")
async def db_session():
    """Provide a clean DB session per test with rollback."""
    engine = create_async_engine(DATABASE_URL, echo=False)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Reset database
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.execute(text("GRANT ALL ON SCHEMA public TO lis"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS citext"))

    # Run alembic migrations with direct PG connection (bypass PgBouncer)
    env = {**os.environ, "DATABASE_URL": DATABASE_URL}
    proc = subprocess.run(
        [".venv/bin/alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
        cwd="/home/ashok/Documents/personal_project/fraud/ss",
        env=env,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"alembic upgrade head failed:\n{proc.stderr}")

    async with async_session() as session:
        yield session

    await engine.dispose()


@pytest.fixture(scope="function")
async def test_user_id(db_session: AsyncSession) -> uuid.UUID:
    """Insert a test user and return its ID for FK references."""
    user_id = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO users (id, email, hashed_password, is_active) "
            "VALUES (:id, :email, :pw, true)"
        ),
        {
            "id": str(user_id),
            "email": f"test_{user_id.hex[:8]}@example.com",
            "pw": "hashed_password_placeholder",
        },
    )
    await db_session.flush()
    return user_id


@pytest.fixture(scope="function")
async def syllabus_session():
    """Provide a syllabus DB session per test."""
    engine = create_async_engine(SYLLABUS_DATABASE_URL, echo=False)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Reset
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.execute(text("GRANT ALL ON SCHEMA public TO lis"))

    # Re-apply the syllabus_items schema (bypasses alembic; see S11 spec).
    # Run as one script via the raw asyncpg connection - the file contains a
    # DO $$ ... $$ block that a naive split on ";" would mangle.
    async with engine.connect() as conn:
        raw = await conn.get_raw_connection()
        await raw.driver_connection.execute(SYLLABUS_SCHEMA_SQL)
        await conn.commit()

    async with async_session() as session:
        yield session

    await engine.dispose()
