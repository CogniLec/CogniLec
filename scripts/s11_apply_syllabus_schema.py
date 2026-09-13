#!/usr/bin/env python3
"""Apply the syllabus_items schema to the live PG-SYLLABUS instance.

Alembic (src/db/migrations/) only targets PG-MAIN (see env.py), so the
PG-SYLLABUS-side table is not tracked by alembic's version table at all.
This script bypasses alembic entirely and applies
docker/postgres/migrations/syllabus/001_syllabus_items.sql directly and
idempotently (the SQL uses IF NOT EXISTS / CREATE TABLE IF NOT EXISTS
throughout, so re-running is always safe).

Usage:
    .venv/bin/python scripts/s11_apply_syllabus_schema.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.ext.asyncio import create_async_engine
from src.core.config import get_settings

SQL_DIR = Path(__file__).resolve().parents[1] / "docker" / "postgres" / "migrations" / "syllabus"
# S50/S52 added 002_syllabus_items_extend.sql on top of S11's 001 file -
# apply every numbered file in this directory, in order, each idempotent.
SQL_PATHS = sorted(SQL_DIR.glob("*.sql"))


async def main() -> None:
    settings = get_settings()

    engine = create_async_engine(settings.SYLLABUS_DATABASE_URL, echo=False)
    try:
        for sql_path in SQL_PATHS:
            sql = sql_path.read_text()
            async with engine.connect() as conn:
                # Run the whole file as one script via the raw asyncpg
                # connection (each file may contain a DO $$ ... $$ block,
                # which a naive split on ";" would mangle; asyncpg's
                # .execute() runs a full multi-statement script as-is via
                # the simple query protocol).
                raw = await conn.get_raw_connection()
                await raw.driver_connection.execute(sql)  # type: ignore[union-attr]
                await conn.commit()
            print(f"Applied {sql_path} to {settings.SYLLABUS_DATABASE_URL!r}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
