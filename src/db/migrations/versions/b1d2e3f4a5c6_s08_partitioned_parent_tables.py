"""S08: convert to partitioned parent tables.

Revision ID: b1d2e3f4a5c6
Revises: c58ea6212bc5
Create Date: 2026-09-12 10:00:00.000000

"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b1d2e3f4a5c6"
down_revision: str | Sequence[str] | None = "c58ea6212bc5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop non-partitioned tables and recreate as PARTITION BY LIST (subject_id)."""
    # Drop existing non-partitioned tables (order: FK dependencies first)
    op.drop_table("note_provenance")
    op.drop_table("note_sections")
    op.drop_table("segments")
    op.drop_table("utterances")

    # utterances - partitioned parent
    op.execute(
        sa.text(
            "CREATE TABLE utterances ("
            "    subject_id UUID NOT NULL,"
            "    id UUID NOT NULL DEFAULT gen_random_uuid(),"
            "    session_id UUID NOT NULL REFERENCES sessions(id),"
            "    seq INTEGER NOT NULL,"
            "    start_ms INTEGER NOT NULL,"
            "    end_ms INTEGER NOT NULL,"
            "    text TEXT NOT NULL,"
            "    asr_confidence DOUBLE PRECISION,"
            "    speaker_tag VARCHAR(10),"
            "    embedding vector(1024),"
            "    embed_model_ver VARCHAR(50) NOT NULL,"
            "    topic_id UUID,"
            "    is_relevant BOOLEAN,"
            "    filter_reason VARCHAR(100),"
            "    outlier_score DOUBLE PRECISION,"
            "    asr_agreement DOUBLE PRECISION,"
            "    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
            "    UNIQUE (subject_id, session_id, seq)"
            ") PARTITION BY LIST (subject_id)"
        )
    )

    # segments - partitioned parent
    op.execute(
        sa.text(
            "CREATE TABLE segments ("
            "    subject_id UUID NOT NULL,"
            "    id UUID NOT NULL DEFAULT gen_random_uuid(),"
            "    session_id UUID NOT NULL REFERENCES sessions(id),"
            "    start_utt UUID NOT NULL,"
            "    end_utt UUID NOT NULL,"
            "    topic_id UUID,"
            "    boundary_score DOUBLE PRECISION,"
            "    confidence DOUBLE PRECISION,"
            "    created_at TIMESTAMPTZ NOT NULL DEFAULT now()"
            ") PARTITION BY LIST (subject_id)"
        )
    )

    # note_sections - partitioned parent
    op.execute(
        sa.text(
            "CREATE TABLE note_sections ("
            "    subject_id UUID NOT NULL,"
            "    id UUID NOT NULL DEFAULT gen_random_uuid(),"
            "    topic_id UUID,"
            "    session_id UUID,"
            "    heading TEXT NOT NULL,"
            "    body_md TEXT NOT NULL,"
            "    depth INTEGER NOT NULL DEFAULT 0,"
            "    ordinal INTEGER NOT NULL,"
            "    embedding vector(1024),"
            "    model_version VARCHAR(50),"
            "    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
            "    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()"
            ") PARTITION BY LIST (subject_id)"
        )
    )

    # note_provenance - partitioned parent
    op.execute(
        sa.text(
            "CREATE TABLE note_provenance ("
            "    subject_id UUID NOT NULL,"
            "    id UUID NOT NULL DEFAULT gen_random_uuid(),"
            "    note_section_id UUID NOT NULL,"
            "    utterance_id UUID NOT NULL,"
            "    created_at TIMESTAMPTZ NOT NULL DEFAULT now()"
            ") PARTITION BY LIST (subject_id)"
        )
    )


def downgrade() -> None:
    """Drop partitioned parent tables and recreate as regular tables."""
    op.drop_table("note_provenance")
    op.drop_table("note_sections")
    op.drop_table("segments")
    op.drop_table("utterances")

    # Recreate as regular (non-partitioned) tables
    op.create_table(
        "utterances",
        sa.Column("subject_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("session_id", sa.UUID(), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=False),
        sa.Column("end_ms", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("asr_confidence", sa.Float(), nullable=True),
        sa.Column("speaker_tag", sa.String(length=10), nullable=True),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(dim=1024), nullable=True),
        sa.Column("embed_model_ver", sa.String(length=50), nullable=False),
        sa.Column("topic_id", sa.UUID(), nullable=True),
        sa.Column("is_relevant", sa.Boolean(), nullable=True),
        sa.Column("filter_reason", sa.String(length=100), nullable=True),
        sa.Column("outlier_score", sa.Float(), nullable=True),
        sa.Column("asr_agreement", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("subject_id", "id"),
        sa.UniqueConstraint("subject_id", "session_id", "seq", name="uq_utterance_session_seq"),
    )
    op.create_table(
        "segments",
        sa.Column("subject_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("session_id", sa.UUID(), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("start_utt", sa.UUID(), nullable=False),
        sa.Column("end_utt", sa.UUID(), nullable=False),
        sa.Column("topic_id", sa.UUID(), nullable=True),
        sa.Column("boundary_score", sa.Float(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("subject_id", "id"),
    )
    op.create_table(
        "note_sections",
        sa.Column("subject_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("topic_id", sa.UUID(), nullable=True),
        sa.Column("session_id", sa.UUID(), nullable=True),
        sa.Column("heading", sa.Text(), nullable=False),
        sa.Column("body_md", sa.Text(), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(dim=1024), nullable=True),
        sa.Column("model_version", sa.String(length=50), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("subject_id", "id"),
    )
    op.create_table(
        "note_provenance",
        sa.Column("subject_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("note_section_id", sa.UUID(), nullable=False),
        sa.Column("utterance_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("subject_id", "id"),
    )
