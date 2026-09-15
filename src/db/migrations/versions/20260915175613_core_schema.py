"""Core schema: users, subjects, sessions, agent_runs.

Revision ID: 20260915175613
Revises:
Create Date: 2026-09-15 17:56:13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import CITEXT

# revision identifiers, used by Alembic.
revision: str = "20260915175613"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("email", CITEXT(), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )

    op.create_table(
        "subjects",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "name", name="uq_subject_user_name"),
    )
    op.create_index("idx_subjects_user_id", "subjects", ["user_id"])

    op.create_table(
        "sessions",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("session_type", sa.String(length=50), nullable=False, server_default="content"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="created"),
        sa.Column("audio_quality", sa.Float(), nullable=True),
        sa.Column("notes_ready", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "session_type IN ('content', 'syllabus', 'mixed')", name="ck_session_type"
        ),
        sa.CheckConstraint(
            "status IN ('created', 'recording', 'transcribed', 'processing', 'complete', 'failed')",
            name="ck_session_status",
        ),
    )
    op.create_index("idx_sessions_subject_id", "sessions", ["subject_id"])

    op.create_table(
        "agent_runs",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.String(length=50), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("tier", sa.Integer(), nullable=True),
        sa.Column("prompt_version", sa.String(length=50), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("outcome", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
    )
    op.create_index("idx_agent_runs_session_id", "agent_runs", ["session_id"])


def downgrade() -> None:
    op.drop_table("agent_runs")
    op.drop_table("sessions")
    op.drop_table("subjects")
    op.drop_table("users")
