"""S33/S34/S35: topics.provisional, segments.cue_metadata/route_target,
sessions.classification_confidence/method/details

Revision ID: a9c1e7f2b4d8
Revises: f1a2b3c4d5e6
Create Date: 2026-09-13 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a9c1e7f2b4d8"
down_revision: str | Sequence[str] | None = "f1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "topics",
        sa.Column("provisional", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.add_column(
        "segments",
        sa.Column("cue_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "segments",
        sa.Column("route_target", sa.String(20), nullable=True),
    )
    op.add_column(
        "sessions",
        sa.Column("classification_confidence", sa.Float(), nullable=True),
    )
    op.add_column(
        "sessions",
        sa.Column("classification_method", sa.String(20), nullable=True),
    )
    op.add_column(
        "sessions",
        sa.Column("classification_details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sessions", "classification_details")
    op.drop_column("sessions", "classification_method")
    op.drop_column("sessions", "classification_confidence")
    op.drop_column("segments", "route_target")
    op.drop_column("segments", "cue_metadata")
    op.drop_column("topics", "provisional")
