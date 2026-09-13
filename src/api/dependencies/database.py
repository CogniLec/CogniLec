"""Database dependencies for FastAPI."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import MainAsyncSession


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session, auto-committing on success."""
    async with MainAsyncSession() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
