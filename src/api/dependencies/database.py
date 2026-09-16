"""Database dependencies for FastAPI."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import RlsAsyncSession, SyllabusAsyncSession


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
