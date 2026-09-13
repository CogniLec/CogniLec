"""S30: topics table with centroid vector, labels, keywords

Revision ID: f1a2b3c4d5e6
Revises: e5d9a3c1f6b7
Create Date: 2026-09-13 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f1a2b3c4d5e6"
down_revision: str | Sequence[str] | None = "e5d9a3c1f6b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create topics table (S30) with HNSW centroid index for S32 matching."""
    op.create_table(
        "topics",
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sessions.id"),
            nullable=True,
        ),
        sa.Column("centroid", Vector(1024), nullable=False),
        sa.Column("label", sa.String(200), nullable=True),
        sa.Column("keywords", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("keyword_scores", postgresql.ARRAY(sa.Float()), nullable=True),
        sa.Column("segment_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("utterance_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_user_edited", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.execute(
        "CREATE INDEX idx_topics_centroid ON topics "
        "USING hnsw (centroid vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
    )
    op.execute("CREATE INDEX idx_topics_subject_id ON topics (subject_id)")


def downgrade() -> None:
    """Drop topics table."""
    op.execute("DROP INDEX IF EXISTS idx_topics_subject_id")
    op.execute("DROP INDEX IF EXISTS idx_topics_centroid")
    op.drop_table("topics")
