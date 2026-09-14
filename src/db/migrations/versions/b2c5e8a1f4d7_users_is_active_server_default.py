"""users.is_active gets a real server-side default

Revision ID: b2c5e8a1f4d7
Revises: f1a4c8e2b9d3
Create Date: 2026-09-14

Found running the app for real (not through a test fixture): `is_active`
only had a Python-side ORM default (`default=True`), never a
`server_default`, so any raw-SQL INSERT bypassing the ORM -- e.g.
`src/api/routes/auth.py`'s `/auth/register` -- violated its NOT NULL
constraint. Adds the missing server-side default so this is safe by
construction for any future caller, in addition to the immediate fix in
auth.py's own INSERT statement.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "b2c5e8a1f4d7"
down_revision: str | None = "f1a4c8e2b9d3"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ALTER COLUMN is_active SET DEFAULT true")


def downgrade() -> None:
    op.execute("ALTER TABLE users ALTER COLUMN is_active DROP DEFAULT")
