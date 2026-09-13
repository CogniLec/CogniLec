"""S48: generated tsvector columns + GIN indexes for hybrid search.

Revision ID: b7e2c4f9a1d5
Revises: a9c1e7f2b4d8
Create Date: 2026-09-13 00:00:00.000000

`utterances`/`note_sections` are LIST partitions on `subject_id` (S08); a
`GENERATED ALWAYS AS (...) STORED` column and a `CREATE INDEX` added to the
partitioned parent are both automatically applied to every existing
partition and inherited by every partition created afterwards (Postgres
partition DDL propagation, no per-partition loop needed here).
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7e2c4f9a1d5"
down_revision: str | Sequence[str] | None = "a9c1e7f2b4d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE utterances ADD COLUMN text_tsv tsvector "
        "GENERATED ALWAYS AS (to_tsvector('english', text)) STORED"
    )
    op.execute("CREATE INDEX ix_utterances_text_tsv ON utterances USING GIN (text_tsv)")

    op.execute(
        "ALTER TABLE note_sections ADD COLUMN body_tsv tsvector "
        "GENERATED ALWAYS AS (to_tsvector('english', heading || ' ' || body_md)) STORED"
    )
    op.execute("CREATE INDEX ix_note_sections_body_tsv ON note_sections USING GIN (body_tsv)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_note_sections_body_tsv")
    op.execute("ALTER TABLE note_sections DROP COLUMN IF EXISTS body_tsv")
    op.execute("DROP INDEX IF EXISTS ix_utterances_text_tsv")
    op.execute("ALTER TABLE utterances DROP COLUMN IF EXISTS text_tsv")
