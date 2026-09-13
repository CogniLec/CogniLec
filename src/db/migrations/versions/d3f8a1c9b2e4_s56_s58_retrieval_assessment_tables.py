"""S56-S58: note_links, questions, flashcards/flashcard_reviews + read-only role.

Revision ID: d3f8a1c9b2e4
Revises: b7e2c4f9a1d5
Create Date: 2026-09-13 00:00:00.000000

Also provisions `lis_readonly` (T56.2/T57.4): a NOSUPERUSER/NOBYPASSRLS role
granted SELECT only, so A3/A5 retrieval connections through it get a real,
Postgres-enforced write rejection - independent of the RLS-bypass gap
tracked in docs/gaps.md #4 (which concerns the superuser `lis` role
specifically bypassing row-level security, a different mechanism from the
table-level GRANTs used here).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d3f8a1c9b2e4"
down_revision: str | Sequence[str] | None = "b7e2c4f9a1d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

READONLY_ROLE = "lis_readonly"
READONLY_PASSWORD = "lis_readonly_dev"


def upgrade() -> None:
    op.create_table(
        "note_links",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "subject_id",
            sa.UUID(),
            sa.ForeignKey("subjects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "from_session_id",
            sa.UUID(),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "to_session_id",
            sa.UUID(),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("link_type", sa.String(length=30), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_note_links_subject_id", "note_links", ["subject_id"])

    op.create_table(
        "questions",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "subject_id",
            sa.UUID(),
            sa.ForeignKey("subjects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("question_type", sa.String(length=20), nullable=False),
        sa.Column("options", postgresql.JSONB(), nullable=True),
        sa.Column("correct_answer", sa.Text(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("difficulty", sa.String(length=10), nullable=False),
        sa.Column("topic_tags", postgresql.JSONB(), nullable=False),
        sa.Column("answerable", sa.Boolean(), nullable=False),
        sa.Column("answerability_rationale", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_questions_subject_id", "questions", ["subject_id"])

    op.create_table(
        "flashcards",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "subject_id",
            sa.UUID(),
            sa.ForeignKey("subjects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("topic_label", sa.String(length=200), nullable=False),
        sa.Column("front", sa.Text(), nullable=False),
        sa.Column("back", sa.Text(), nullable=False),
        sa.Column("fsrs_state", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fsrs_step", sa.Integer(), nullable=True),
        sa.Column("fsrs_stability", sa.Float(), nullable=True),
        sa.Column("fsrs_difficulty", sa.Float(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_review_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_flashcards_subject_id", "flashcards", ["subject_id"])

    op.create_table(
        "flashcard_reviews",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "flashcard_id",
            sa.UUID(),
            sa.ForeignKey("flashcards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_flashcard_reviews_flashcard_id", "flashcard_reviews", ["flashcard_id"])

    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{READONLY_ROLE}') THEN
                CREATE ROLE {READONLY_ROLE} LOGIN PASSWORD '{READONLY_PASSWORD}'
                    NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
            END IF;
        END
        $$;
        """
    )
    op.execute(f"GRANT CONNECT ON DATABASE lis_main TO {READONLY_ROLE}")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {READONLY_ROLE}")
    op.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {READONLY_ROLE}")
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO {READONLY_ROLE}"
    )


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {READONLY_ROLE}")
    op.execute(f"REVOKE ALL ON SCHEMA public FROM {READONLY_ROLE}")
    op.execute(f"REVOKE ALL ON DATABASE lis_main FROM {READONLY_ROLE}")

    op.drop_index("ix_flashcard_reviews_flashcard_id", table_name="flashcard_reviews")
    op.drop_table("flashcard_reviews")
    op.drop_index("ix_flashcards_subject_id", table_name="flashcards")
    op.drop_table("flashcards")
    op.drop_index("ix_questions_subject_id", table_name="questions")
    op.drop_table("questions")
    op.drop_index("ix_note_links_subject_id", table_name="note_links")
    op.drop_table("note_links")
