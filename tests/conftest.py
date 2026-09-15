"""Shared fixtures for S07 integration/unit tests."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Generator

import pytest
import pytest_asyncio
import sqlalchemy
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from testcontainers.postgres import PostgresContainer


def _alembic_config(sync_url: str) -> Config:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", sync_url)
    return cfg


@pytest.fixture(scope="session")
def postgres_container() -> Generator[PostgresContainer, None, None]:
    with PostgresContainer("postgres:16-alpine") as container:
        yield container


@pytest.fixture(scope="session")
def async_database_url(postgres_container: PostgresContainer) -> str:
    sync_url = postgres_container.get_connection_url()
    return sync_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://")


@pytest.fixture(scope="session")
def _migrated_schema(postgres_container: PostgresContainer, async_database_url: str) -> None:
    sync_url = postgres_container.get_connection_url()
    engine = sqlalchemy.create_engine(sync_url)
    with engine.begin() as conn:
        conn.execute(sqlalchemy.text("CREATE EXTENSION IF NOT EXISTS citext"))
        conn.execute(sqlalchemy.text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))
    engine.dispose()

    cfg = _alembic_config(async_database_url)
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session")
def engine(async_database_url: str, _migrated_schema: None) -> Generator[AsyncEngine, None, None]:
    eng = create_async_engine(async_database_url)
    yield eng


@pytest_asyncio.fixture
async def db_session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Function-scoped session isolated via a rolled-back outer transaction.

    The session runs its own commits/rollbacks as SAVEPOINTs (join_transaction_mode)
    so a repo-level rollback on a constraint violation doesn't abort the outer
    per-test transaction, which is rolled back wholesale at teardown.
    """
    connection = await engine.connect()
    trans = await connection.begin()
    session_factory = async_sessionmaker(
        bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    session = session_factory()

    try:
        yield session
    finally:
        await session.close()
        await trans.rollback()
        await connection.close()
