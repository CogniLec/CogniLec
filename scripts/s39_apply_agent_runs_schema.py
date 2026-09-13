#!/usr/bin/env python3
"""S39 — Apply the agent_runs table migration to PG-MAIN.

Usage: python scripts/s39_apply_agent_runs_schema.py
Reads DATABASE_URL (sync-compatible, psycopg-style) from the environment,
falling back to src.core.config.Settings.DATABASE_URL with the asyncpg
driver stripped for use with a plain psycopg/asyncpg connection.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import asyncpg

MIGRATION_PATH = Path(__file__).parent.parent / "docker/postgres/migrations/0001_agent_runs.sql"


async def main() -> None:
    dsn = os.environ.get("DATABASE_URL", "postgresql://lis:lis@localhost:5432/lis")
    dsn = dsn.replace("postgresql+asyncpg://", "postgresql://")
    sql = MIGRATION_PATH.read_text()

    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(sql)
        print(f"applied {MIGRATION_PATH.name}")
    finally:
        await conn.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (OSError, asyncpg.PostgresError) as exc:
        print(f"failed to apply agent_runs schema: {exc}", file=sys.stderr)
        sys.exit(1)
