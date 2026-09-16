"""Provision lis_app: a NOSUPERUSER/NOBYPASSRLS runtime role for the app.

Revision ID: c4d8e2a6f1b9
Revises: b2c5e8a1f4d7
Create Date: 2026-09-16 00:00:00.000000

Closes docs/gaps.md #4: the `lis` role used at runtime is a Postgres
SUPERUSER with BYPASSRLS (set up for migrations, which genuinely need DDL
rights), so RLS policies on `subjects`/`sessions`/`utterances`/`segments`/
`note_sections`/`note_provenance` (migration 8b67f8790b48) were never
actually enforced by Postgres itself -- only by the explicit ownership
checks in src/api/dependencies/ownership.py.

`lis_app` gets full DML (SELECT/INSERT/UPDATE/DELETE) on every table, but
deliberately no DDL/role-management rights, and no BYPASSRLS -- so on the
6 RLS-policy tables, Postgres itself now denies a query for rows outside
`app.user_id`'s ownership, independent of any application code. Migrations
still run as the superuser `lis` (unchanged) via DATABASE_URL; the app's
per-request connection switches to `lis_app` via the new RLS_DATABASE_URL
setting (src/core/config.py) -- see src/db/session.py.

Also adds a `postgres_fdw` USER MAPPING FOR lis_app on the syllabus_server
(migration a2c7d4e9f1b3 only mapped `lis`) -- without one, any query
against the `syllabus_items` foreign table through the new lis_app
connection fails with "no user mapping found", since FDW resolves remote
credentials per connecting local role.
"""

from collections.abc import Sequence

from alembic import op
from src.core.config import get_settings

# revision identifiers, used by Alembic.
revision: str = "c4d8e2a6f1b9"
down_revision: str | Sequence[str] | None = "b2c5e8a1f4d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "lis_app"
APP_PASSWORD = "lis_app_dev"
FDW_SERVER_NAME = "syllabus_server"


def upgrade() -> None:
    settings = get_settings()

    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                CREATE ROLE {APP_ROLE} LOGIN PASSWORD '{APP_PASSWORD}'
                    NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
            END IF;
        END
        $$;
        """
    )
    op.execute(f"GRANT CONNECT ON DATABASE lis_main TO {APP_ROLE}")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}")
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {APP_ROLE}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {APP_ROLE}"
    )

    # FDW: this DO block only runs if the S11 server exists -- harmless
    # no-op on a fresh test DB that hasn't run S11's migration for some
    # reason, but every normal `alembic upgrade head` run has it by now.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_foreign_server WHERE srvname = '{FDW_SERVER_NAME}') THEN
                EXECUTE format(
                    'CREATE USER MAPPING FOR {APP_ROLE} SERVER {FDW_SERVER_NAME} '
                    'OPTIONS (user %L, password %L)',
                    '{settings.SYLLABUS_FDW_USER}', '{settings.SYLLABUS_FDW_PASSWORD}'
                );
            END IF;
        EXCEPTION WHEN duplicate_object THEN
            NULL;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute(f"DROP USER MAPPING IF EXISTS FOR {APP_ROLE} SERVER {FDW_SERVER_NAME}")
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {APP_ROLE}")
    op.execute(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {APP_ROLE}")
    op.execute(f"REVOKE ALL ON SCHEMA public FROM {APP_ROLE}")
    op.execute(f"REVOKE CONNECT ON DATABASE lis_main FROM {APP_ROLE}")
