"""S50 — application-level write-authority guard for PG-SYLLABUS (DB-3).

Defense-in-depth alongside the DB-role GRANT restriction (see
``docker/postgres/migrations/syllabus/002_syllabus_items_extend.sql``): only
code running inside ``DB3WriteGuard.a6_write_context()`` may perform a
``syllabus_items`` write through ``SyllabusRepository``. Any other caller
gets ``PermissionError`` before a single query is issued.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar


class DB3WriteGuard:
    """Enforce that only the A6 syllabus-extraction path writes to DB-3."""

    _a6_context: ContextVar[bool] = ContextVar("a6_write_context", default=False)

    @classmethod
    @contextmanager
    def a6_write_context(cls) -> Iterator[None]:
        token = cls._a6_context.set(True)
        try:
            yield
        finally:
            cls._a6_context.reset(token)

    @classmethod
    def check_write_authority(cls) -> None:
        if not cls._a6_context.get():
            msg = "DB-3 write rejected: only A6 agent may write to syllabus store (FR-3.8)"
            raise PermissionError(msg)
