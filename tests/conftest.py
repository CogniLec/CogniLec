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
_SYLLABUS_MIGRATIONS_DIR = (
    Path(__file__).resolve().parents[1] / "docker" / "postgres" / "migrations" / "syllabus"
)
# S50/S52 extended the S11 schema (item_type/weight_pct/.../a6_writer role) in
# 002_syllabus_items_extend.sql - apply both, in order, like the real
# out-of-band apply script (scripts/s11_apply_syllabus_schema.py) does.
SYLLABUS_SCHEMA_SQL = "\n".join(
    (_SYLLABUS_MIGRATIONS_DIR / name).read_text()
    for name in ("001_syllabus_items.sql", "002_syllabus_items_extend.sql")
)

# Connect directly to PostgreSQL, bypassing PgBouncer.
#
# These point at dedicated lis_test/lis_syllabus_test databases, NOT
# lis_main/lis_syllabus (the live app's real databases) -- this fixture's
# DROP SCHEMA public CASCADE below previously ran directly against the
# live databases, silently wiping every real registered user/subject/
# anything else on every test run. lis_test/lis_syllabus_test are
# provisioned by docker/postgres/init-main.sql and init-syllabus.sql
# (on a fresh volume) or created manually otherwise -- see those files.
DATABASE_URL = "postgresql+asyncpg://lis:lis_dev@localhost:5434/lis_test"
SYLLABUS_DATABASE_URL = "postgresql+asyncpg://lis:lis_dev@localhost:5435/lis_syllabus_test"


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

    # Run alembic migrations with direct PG connection (bypass PgBouncer).
    # SYLLABUS_DB_NAME override matters too: migration a2c7d4e9f1b3 (S11)
    # creates the postgres_fdw foreign server's remote `dbname` option from
    # this setting -- without pointing it at lis_syllabus_test too, the FDW
    # foreign table on lis_test would read from the real lis_syllabus
    # instead of the isolated test database SYLLABUS_DATABASE_URL below
    # actually writes to, and any FDW-read test finds nothing (confirmed
    # live: this exact mismatch broke test_syllabus.py::test_fdw_query).
    env = {
        **os.environ,
        "DATABASE_URL": DATABASE_URL,
        "SYLLABUS_DB_NAME": "lis_syllabus_test",
    }
    proc = subprocess.run(
        [".venv/bin/alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[1]),
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
