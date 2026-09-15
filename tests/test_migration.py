"""T07.5 — Alembic upgrade head -> downgrade base -> upgrade head leaves a clean DB."""

from __future__ import annotations

import sqlalchemy
from alembic import command
from alembic.config import Config
from testcontainers.postgres import PostgresContainer

EXPECTED_TABLES = {"agent_runs", "sessions", "subjects", "users"}


def _create_extensions(sync_url: str) -> None:
    engine = sqlalchemy.create_engine(sync_url)
    with engine.begin() as conn:
        conn.execute(sqlalchemy.text("CREATE EXTENSION IF NOT EXISTS citext"))
        conn.execute(sqlalchemy.text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))
    engine.dispose()


def _table_names(sync_url: str) -> set[str]:
    engine = sqlalchemy.create_engine(sync_url)
    names = set(sqlalchemy.inspect(engine).get_table_names())
    engine.dispose()
    return names


class TestUpgradeDowngradeRoundtrip:
    def test_upgrade_downgrade_roundtrip(self) -> None:
        with PostgresContainer("postgres:16-alpine") as container:
            sync_url = container.get_connection_url()
            _create_extensions(sync_url)

            async_url = sync_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
            cfg = Config("alembic.ini")
            cfg.set_main_option("sqlalchemy.url", async_url)

            command.upgrade(cfg, "head")
            assert _table_names(sync_url) >= EXPECTED_TABLES

            command.downgrade(cfg, "base")
            assert not (EXPECTED_TABLES & _table_names(sync_url))

            command.upgrade(cfg, "head")
            assert _table_names(sync_url) >= EXPECTED_TABLES
