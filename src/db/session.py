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

# Main database engine (PG-MAIN via PgBouncer)
main_engine: AsyncEngine = create_async_engine(
    settings.DATABASE_URL,
    poolclass=NullPool,  # PgBouncer handles pooling
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
    """Get syllabus database session (read-only via FDW)."""
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
    async with syllabus_engine.begin() as conn:
        await conn.execute(text("SELECT 1"))


async def close_db() -> None:
    """Close database connections (called at shutdown)."""
    await main_engine.dispose()
    await syllabus_engine.dispose()
