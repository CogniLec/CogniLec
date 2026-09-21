"""note_quality_traces (append-only) + users.allow_cloud_scoring consent flag.

Revision ID: d1a7c3e5b9f2
Revises: c4d8e2a6f1b9
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d1a7c3e5b9f2"
down_revision = "c4d8e2a6f1b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "note_quality_traces",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reward", sa.Float, nullable=False),
        sa.Column("terms", postgresql.JSONB, nullable=False),
        sa.Column("judged", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("config_version", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_note_quality_traces_session_id", "note_quality_traces", ["session_id"])
    op.execute(
        "CREATE RULE note_quality_traces_no_update AS "
        "ON UPDATE TO note_quality_traces DO INSTEAD NOTHING"
    )
    op.execute(
        "CREATE RULE note_quality_traces_no_delete AS "
        "ON DELETE TO note_quality_traces DO INSTEAD NOTHING"
    )
    op.add_column(
        "users",
        sa.Column("allow_cloud_scoring", sa.Boolean, nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("users", "allow_cloud_scoring")
    op.execute("DROP RULE note_quality_traces_no_delete ON note_quality_traces")
    op.execute("DROP RULE note_quality_traces_no_update ON note_quality_traces")
    op.drop_table("note_quality_traces")
