"""S11: postgres_fdw link to PG-SYLLABUS (syllabus_items foreign table)

Revision ID: a2c7d4e9f1b3
Revises: f4a1b9c3d7e2
Create Date: 2026-09-12

Installs postgres_fdw on PG-MAIN and wires up a read-only foreign table
for ``syllabus_items``, which physically lives on the separate PG-SYLLABUS
instance (see docker/postgres/migrations/syllabus/001_syllabus_items.sql,
applied out-of-band by scripts/s11_apply_syllabus_schema.py - alembic here
only ever targets PG-MAIN, per src/db/migrations/env.py).

This lets PG-MAIN read-through-join its local ``subjects`` table against
foreign ``syllabus_items`` rows in a single query (S11 spec section 5's FDW
Query Pattern / T11.3), while all writes to syllabus_items still go through
a direct PG-SYLLABUS connection (SyllabusRepository.create_item /
update_coverage / delete_item, via src.db.session.get_syllabus_session) -
per S50's "A6 is sole writer to DB-3". The user mapping and foreign table
are therefore deliberately SELECT-only (T11.5): INSERT/UPDATE/DELETE are
revoked from the foreign table so the FDW path can never be used to write.

Credentials for the user mapping are sourced from Settings (SYLLABUS_DB_*),
never hardcoded here.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from src.core.config import get_settings

revision: str = "a2c7d4e9f1b3"
down_revision: str | Sequence[str] | None = "f4a1b9c3d7e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FDW_SERVER_NAME = "syllabus_server"
FDW_USER_MAPPING = "lis"
FDW_FOREIGN_TABLE = "syllabus_items"


def upgrade() -> None:
    settings = get_settings()

    op.execute("CREATE EXTENSION IF NOT EXISTS postgres_fdw")

    op.execute(
        f"""
        CREATE SERVER IF NOT EXISTS {FDW_SERVER_NAME}
            FOREIGN DATA WRAPPER postgres_fdw
            OPTIONS (
                host '{settings.SYLLABUS_DB_HOST}',
                port '{settings.SYLLABUS_DB_PORT}',
                dbname '{settings.SYLLABUS_DB_NAME}'
            )
        """
    )

    # CREATE USER MAPPING has no IF NOT EXISTS; drop-then-create keeps this
    # idempotent across repeated upgrades in dev/test.
    # NB: the *local* role in this mapping (FDW_USER_MAPPING, "lis") is
    # PG-MAIN's app role; the *remote* user in OPTIONS is a dedicated
    # read-only role on PG-SYLLABUS (lis_fdw_reader, created by
    # docker/postgres/migrations/syllabus/001_syllabus_items.sql) - not the
    # write-capable SYLLABUS_DB_USER. See T11.5 / module docstring.
    op.execute(f"DROP USER MAPPING IF EXISTS FOR {FDW_USER_MAPPING} SERVER {FDW_SERVER_NAME}")
    op.execute(
        f"""
        CREATE USER MAPPING FOR {FDW_USER_MAPPING}
            SERVER {FDW_SERVER_NAME}
            OPTIONS (
                user '{settings.SYLLABUS_FDW_USER}',
                password '{settings.SYLLABUS_FDW_PASSWORD}'
            )
        """
    )

    op.execute(f"DROP FOREIGN TABLE IF EXISTS {FDW_FOREIGN_TABLE}")
    op.execute(
        f"""
        IMPORT FOREIGN SCHEMA public
            LIMIT TO ({FDW_FOREIGN_TABLE})
            FROM SERVER {FDW_SERVER_NAME}
            INTO public
        """
    )

    # Read-only from PG-MAIN's side (T11.5): grant SELECT only, and be
    # explicit that writes are revoked (belt-and-braces - GRANT SELECT alone
    # never implies INSERT/UPDATE/DELETE, but this documents intent and is
    # safe to re-run).
    op.execute(f"GRANT SELECT ON TABLE {FDW_FOREIGN_TABLE} TO {FDW_USER_MAPPING}")
    op.execute(
        f"REVOKE INSERT, UPDATE, DELETE ON TABLE {FDW_FOREIGN_TABLE} FROM {FDW_USER_MAPPING}"
    )


def downgrade() -> None:
    op.execute(f"DROP FOREIGN TABLE IF EXISTS {FDW_FOREIGN_TABLE}")
    op.execute(f"DROP USER MAPPING IF EXISTS FOR {FDW_USER_MAPPING} SERVER {FDW_SERVER_NAME}")
    op.execute(f"DROP SERVER IF EXISTS {FDW_SERVER_NAME} CASCADE")
    op.execute("DROP EXTENSION IF EXISTS postgres_fdw")
