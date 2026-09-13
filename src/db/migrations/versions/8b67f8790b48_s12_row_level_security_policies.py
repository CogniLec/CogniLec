"""S12: row-level security policies

Revision ID: 8b67f8790b48
Revises: b1d2e3f4a5c6
Create Date: 2026-09-12 02:40:22.648890

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8b67f8790b48"
down_revision: str | Sequence[str] | None = "b1d2e3f4a5c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_RLS_TABLES = (
    "subjects",
    "sessions",
    "utterances",
    "segments",
    "note_sections",
    "note_provenance",
)


def upgrade() -> None:
    """Enable RLS and create user-isolation policies."""
    # Enable RLS on all data tables
    for table in _RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")

    # Force RLS for table owners (superuser bypass is disabled by default,
    # but FORCE ensures even table owners are subject to policies)
    for table in _RLS_TABLES:
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    # --- Policies ---

    # subjects: direct user_id match
    op.execute("""
        CREATE POLICY user_isolation_subjects ON subjects
        USING (user_id = current_setting('app.user_id')::UUID)
    """)

    # sessions: via subject ownership
    op.execute("""
        CREATE POLICY user_isolation_sessions ON sessions
        USING (subject_id IN (
            SELECT id FROM subjects WHERE user_id = current_setting('app.user_id')::UUID
        ))
    """)

    # utterances: via subject ownership
    op.execute("""
        CREATE POLICY user_isolation_utterances ON utterances
        USING (subject_id IN (
            SELECT id FROM subjects WHERE user_id = current_setting('app.user_id')::UUID
        ))
    """)

    # segments: via subject ownership
    op.execute("""
        CREATE POLICY user_isolation_segments ON segments
        USING (subject_id IN (
            SELECT id FROM subjects WHERE user_id = current_setting('app.user_id')::UUID
        ))
    """)

    # note_sections: via subject ownership
    op.execute("""
        CREATE POLICY user_isolation_note_sections ON note_sections
        USING (subject_id IN (
            SELECT id FROM subjects WHERE user_id = current_setting('app.user_id')::UUID
        ))
    """)

    # note_provenance: via subject ownership
    op.execute("""
        CREATE POLICY user_isolation_note_provenance ON note_provenance
        USING (subject_id IN (
            SELECT id FROM subjects WHERE user_id = current_setting('app.user_id')::UUID
        ))
    """)


def downgrade() -> None:
    """Drop RLS policies and disable RLS."""
    for table in _RLS_TABLES:
        op.execute(f"DROP POLICY IF EXISTS user_isolation_{table} ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
