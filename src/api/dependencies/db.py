"""Database session dependency."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import get_main_session


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with get_main_session() as session:
        yield session
