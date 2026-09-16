"""Database dependencies for FastAPI."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import MainAsyncSession, RlsAsyncSession, SyllabusAsyncSession


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session, auto-committing on success.

    Uses `RlsAsyncSession` (the `lis_app` role: NOSUPERUSER NOBYPASSRLS,
    migration c4d8e2a6f1b9) rather than the superuser `lis` role used for
    migrations -- gap #4: RLS policies are only genuinely enforced by
    Postgres when the connecting role isn't a superuser/BYPASSRLS.
    """
    async with RlsAsyncSession() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_ddl_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a superuser (`lis`) session for the rare route that genuinely
    needs DDL rights -- currently just create_subject's partition
    provisioning (src/db/partitions/provisioner.py runs `CREATE TABLE ...
    PARTITION OF ...`), which `lis_app` (get_db_session, gap #4) cannot do
    by design.

    Deliberately a real, overridable FastAPI dependency rather than routes
    importing MainAsyncSession directly -- confirmed live: a route that
    imports and calls MainAsyncSession() itself bypasses
    app.dependency_overrides entirely, so tests using a different (test)
    database via an overridden get_db_session were silently still hitting
    the real dev database through this path, causing a foreign-key
    violation (the test's user only existed in the test's own session).
    """
    async with MainAsyncSession() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_syllabus_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a direct PG-SYLLABUS session (S50/S51 A6 write path)."""
    async with SyllabusAsyncSession() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
