"""S65-S69: corrections table, immutability rule, agent_runs.adapter_version

Revision ID: c4e7f2a9b6d1
Revises: b3d6e8f1a4c7
Create Date: 2026-09-13

S65 adds `corrections` - the append-only training-signal audit trail for
every one of the spec's six capture points (A1 relevance override, topic
label edit, topic split/merge, syllabus alignment correction, image
rejection, note edit). T65.2 requires corrections to be immutable and
append-only, not just editable-in-theory - enforced at the DB level with
PostgreSQL rules that turn UPDATE/DELETE into no-ops (RAISE EXCEPTION would
also work, but a same-transaction rule keeps this consistent with `lis`
being a superuser role in this dev environment per gap #4 - a rule can't be
bypassed by superuser the way a permission grant could).

S69 adds `agent_runs.adapter_version` (T69.6: adapter version recorded on
every agent_runs row) - nullable because most agents never load a LoRA
adapter; NULL means base-model-only.

`corrections.user_id`'s FK has no ON DELETE action (defaults to RESTRICT):
ON DELETE SET NULL would make Postgres issue an UPDATE against `corrections`
whenever a referenced user is deleted, and that UPDATE collides with the
immutability rule below - Postgres's FK enforcement machinery expects the
SET NULL UPDATE to actually apply and raises `InternalServerError:
referential integrity query ... gave unexpected result` when the rule
silently no-ops it instead. RESTRICT only ever runs a existence-check
SELECT, which the rule doesn't touch.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "c4e7f2a9b6d1"
down_revision: str | None = "b3d6e8f1a4c7"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "corrections",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("correction_type", sa.String(length=50), nullable=False),
        sa.Column("subject_id", sa.UUID(), nullable=True),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("source_id", sa.UUID(), nullable=True),
        sa.Column("original_value", JSONB(), nullable=False),
        sa.Column("corrected_value", JSONB(), nullable=False),
        sa.Column("context", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "consent_for_training", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.CheckConstraint(
            "correction_type IN ('a1_relevance_override', 'topic_label_edit', "
            "'topic_split_merge', 'syllabus_alignment', 'image_rejection', 'note_edit')",
            name="ck_corrections_type",
        ),
    )
    op.create_index("ix_corrections_type", "corrections", ["correction_type"])
    op.create_index("ix_corrections_subject", "corrections", ["subject_id"])
    op.create_index("ix_corrections_user", "corrections", ["user_id"])

    op.execute("CREATE RULE corrections_no_update AS ON UPDATE TO corrections DO INSTEAD NOTHING")
    op.execute("CREATE RULE corrections_no_delete AS ON DELETE TO corrections DO INSTEAD NOTHING")

    op.add_column("agent_runs", sa.Column("adapter_version", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_runs", "adapter_version")
    op.execute("DROP RULE IF EXISTS corrections_no_delete ON corrections")
    op.execute("DROP RULE IF EXISTS corrections_no_update ON corrections")
    op.drop_index("ix_corrections_user", table_name="corrections")
    op.drop_index("ix_corrections_subject", table_name="corrections")
    op.drop_index("ix_corrections_type", table_name="corrections")
    op.drop_table("corrections")
