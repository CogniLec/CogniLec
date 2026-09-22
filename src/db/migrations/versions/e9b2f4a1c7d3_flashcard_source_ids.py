"""flashcards.source_result_ids - provenance for the quality-loop validity term.

Revision ID: e9b2f4a1c7d3
Revises: d1a7c3e5b9f2
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e9b2f4a1c7d3"
down_revision = "d1a7c3e5b9f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "flashcards",
        sa.Column(
            "source_result_ids",
            postgresql.JSONB,
            nullable=False,
            server_default="[]",
        ),
    )


def downgrade() -> None:
    op.drop_column("flashcards", "source_result_ids")
