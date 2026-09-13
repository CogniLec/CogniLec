"""S19: add words JSONB column to utterances (word-level ASR timestamps)

Revision ID: d3f8a1b2c9e4
Revises: 8b67f8790b48
Create Date: 2026-09-12 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "d3f8a1b2c9e4"
down_revision: str | Sequence[str] | None = "8b67f8790b48"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add words JSONB column to the (partitioned) utterances table.

    ALTER TABLE on a partitioned parent propagates the column to all existing
    and future partitions automatically.
    """
    op.add_column(
        "utterances",
        sa.Column(
            "words",
            JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    """Drop the words column."""
    op.drop_column("utterances", "words")
