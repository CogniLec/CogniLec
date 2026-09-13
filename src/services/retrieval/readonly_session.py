"""S56/S57 — a genuinely restricted DB session for A3/A5 retrieval.

`lis_readonly` (migration `d3f8a1c9b2e4`) is a real, non-superuser Postgres
role granted `SELECT` only. A write through a connection authenticated as
this role fails with `InsufficientPrivilegeError` at the database itself
(T56.2/T57.4) - this is independent of the RLS-bypass gap in docs/gaps.md
#4, which is about the separate, superuser `lis` role skipping row-level
security specifically.

RLS policies on `subjects`/`sessions`/`utterances`/`segments`/
`note_sections`/`note_provenance` (S12) key off the `app.user_id` session
variable, so it must be set on this connection before querying those
tables - `open_readonly_session` does this once per session.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def build_readonly_url(base_url: str, ro_user: str, ro_password: str) -> str:
    """Swap the credentials in `base_url` for the read-only role, keeping host/db."""
    scheme_and_rest = base_url.split("://", 1)
    _, rest = scheme_and_rest
    _, host_and_db = rest.split("@", 1)
    return f"{base_url.split('://')[0]}://{ro_user}:{ro_password}@{host_and_db}"


def make_readonly_engine(readonly_url: str) -> AsyncEngine:
    return create_async_engine(readonly_url, pool_pre_ping=True)


@asynccontextmanager
async def open_readonly_session(
    engine: AsyncEngine, user_id: uuid.UUID
) -> AsyncIterator[AsyncSession]:
    """Yield an `AsyncSession` bound to the read-only role, scoped to `user_id`."""
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        # `SET` doesn't accept bound parameters; `user_id` is a `uuid.UUID`
        # (never raw user input) so interpolating its `str()` is safe.
        await session.execute(text(f"SET app.user_id = '{user_id}'"))
        yield session
