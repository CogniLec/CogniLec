"""S75: partition_operations audit log for topic merge/split

Revision ID: a7c2e9f4b1d8
Revises: c4e7f2a9b6d1
Create Date: 2026-09-13

T75.4 requires every partition merge/split to be recorded in an audit log
with before/after state; T75.5 requires a merge to be reversible from that
record. `partition_operations` stores both states as JSONB snapshots
(topic ids, labels, centroids, member session ids) so
`src.services.clustering.partition_ops.reverse_merge` can rebuild the
pre-merge topics without re-deriving them.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "a7c2e9f4b1d8"
down_revision: str | None = "c4e7f2a9b6d1"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "partition_operations",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("subject_id", sa.UUID(), nullable=False),
        sa.Column("operation_type", sa.String(length=20), nullable=False),
        sa.Column("before_state", JSONB(), nullable=False),
        sa.Column("after_state", JSONB(), nullable=False),
        sa.Column("performed_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("reverted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "operation_type IN ('merge', 'split')", name="ck_partition_op_type"
        ),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["performed_by"], ["users.id"]),
    )
    op.create_index("ix_partition_operations_subject", "partition_operations", ["subject_id"])


def downgrade() -> None:
    op.drop_index("ix_partition_operations_subject", table_name="partition_operations")
    op.drop_table("partition_operations")
