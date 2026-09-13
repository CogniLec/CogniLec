"""S23: session failure tracking and retry columns

Revision ID: e5d9a3c1f6b7
Revises: a2c7d4e9f1b3
Create Date: 2026-09-12 13:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5d9a3c1f6b7"
down_revision: str | Sequence[str] | None = "a2c7d4e9f1b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add failure/retry tracking columns to sessions (S23 state machine)."""
    op.add_column("sessions", sa.Column("failure_reason", sa.String(500), nullable=True))
    op.add_column("sessions", sa.Column("failure_stage", sa.String(50), nullable=True))
    op.add_column(
        "sessions",
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("sessions", sa.Column("last_retry_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Drop failure/retry tracking columns."""
    op.drop_column("sessions", "last_retry_at")
    op.drop_column("sessions", "retry_count")
    op.drop_column("sessions", "failure_stage")
    op.drop_column("sessions", "failure_reason")
