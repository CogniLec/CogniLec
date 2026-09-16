"""Database connection and session management"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from src.core.config import get_settings

settings = get_settings()

# Main database engine (PG-MAIN via PgBouncer). Superuser `lis` -- used
# for migrations (src/db/migrations/env.py) and anything that genuinely
# needs DDL. Not used for per-request app queries; see rls_engine below.
main_engine: AsyncEngine = create_async_engine(
    settings.DATABASE_URL,
    poolclass=NullPool,  # PgBouncer handles pooling
    echo=settings.DEBUG,
    pool_pre_ping=True,
)

# gap #4 fix: the app's actual runtime connection, as `lis_app`
# (NOSUPERUSER NOBYPASSRLS, migration c4d8e2a6f1b9) instead of the
# superuser `lis` -- so RLS policies on subjects/sessions/utterances/
# segments/note_sections/note_provenance are genuinely enforced by
# Postgres, not just by application-level ownership checks.
rls_engine: AsyncEngine = create_async_engine(
    settings.RLS_DATABASE_URL,
    poolclass=NullPool,
    echo=settings.DEBUG,
    pool_pre_ping=True,
)

# Syllabus database engine (PG-SYLLABUS direct)
syllabus_engine: AsyncEngine = create_async_engine(
    settings.SYLLABUS_DATABASE_URL,
    poolclass=NullPool,
    echo=settings.DEBUG,
    pool_pre_ping=True,
)

# Session factories
MainAsyncSession = async_sessionmaker(main_engine, class_=AsyncSession, expire_on_commit=False)
RlsAsyncSession = async_sessionmaker(rls_engine, class_=AsyncSession, expire_on_commit=False)

SyllabusAsyncSession = async_sessionmaker(
    syllabus_engine, class_=AsyncSession, expire_on_commit=False
)


@asynccontextmanager
async def get_main_session() -> AsyncGenerator[AsyncSession, None]:
    """Get main database session with RLS user context."""
    async with MainAsyncSession() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def get_syllabus_session() -> AsyncGenerator[AsyncSession, None]:
    """Get a DIRECT session to PG-SYLLABUS (read/write).

    This is a plain direct connection, not FDW - it's the connection
    ``SyllabusRepository`` uses to write syllabus_items (S50: "A6 is sole
    writer to DB-3"). The read-only, FDW-backed path is separate: it lives
    on PG-MAIN (see the ``syllabus_items`` foreign table created by
    migration a2c7d4e9f1b3 and ``SyllabusFdwReader`` in
    src/db/repositories/syllabus_repo.py), and is queried via
    ``get_main_session``, not this function.
    """
    async with SyllabusAsyncSession() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Initialize database connections (called at startup)."""
    # Test connections
    async with main_engine.begin() as conn:
        await conn.execute(text("SELECT 1"))
    async with rls_engine.begin() as conn:
        await conn.execute(text("SELECT 1"))
    async with syllabus_engine.begin() as conn:
        await conn.execute(text("SELECT 1"))


async def close_db() -> None:
    """Close database connections (called at shutdown)."""
    await main_engine.dispose()
    await rls_engine.dispose()
    await syllabus_engine.dispose()
