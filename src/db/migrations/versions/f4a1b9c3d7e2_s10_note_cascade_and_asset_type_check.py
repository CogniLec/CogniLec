"""S10 fix: cascade delete from note_sections, asset_type check constraint

Revision ID: f4a1b9c3d7e2
Revises: d3f8a1b2c9e4
Create Date: 2026-09-12

The original S10 migration (c58ea6212bc5) created note_sections,
note_provenance and note_assets with no foreign keys linking children back
to note_sections, and no check constraint on note_assets.asset_type. Per
the S10 spec (T10.3, T10.5), deleting a note section must cascade to its
provenance links and assets, and unknown asset types must be rejected.

Also fixes a real bug found while wiring this up: S08's migration
(b1d2e3f4a5c6) recreated utterances/segments/note_sections/note_provenance
as raw-SQL `PARTITION BY LIST (subject_id)` parent tables but dropped their
primary keys and never restored them (utterances kept a plain UNIQUE
constraint; segments/note_sections/note_provenance ended up with no key at
all). A composite FK from note_assets/note_provenance to note_sections
requires note_sections to have a real unique/PK constraint on
(subject_id, id), so this migration adds the missing primary keys back to
all four partitioned parents (PartitionProvisioner never creates PK/unique
constraints itself, only HNSW indexes, so this doesn't conflict with it).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f4a1b9c3d7e2"
down_revision: str | Sequence[str] | None = "d3f8a1b2c9e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


ASSET_TYPES = (
    "web_image",
    "generated",
    "board_photo",
    "upload",
    "diagram",
    "ocr_upload",
)


def upgrade() -> None:
    # Restore the primary keys S08's raw-SQL partition rewrite dropped and
    # never recreated. Required before the composite FKs below can exist.
    op.execute(
        "ALTER TABLE note_sections ADD CONSTRAINT pk_note_sections PRIMARY KEY (subject_id, id)"
    )
    op.execute(
        "ALTER TABLE note_provenance ADD CONSTRAINT pk_note_provenance PRIMARY KEY (subject_id, id)"
    )
    op.execute("ALTER TABLE segments ADD CONSTRAINT pk_segments PRIMARY KEY (subject_id, id)")
    op.execute("ALTER TABLE utterances ADD CONSTRAINT pk_utterances PRIMARY KEY (subject_id, id)")

    # note_assets has no subject_id column yet; add it, backfill from the
    # existing note_sections join, then make it required so the composite
    # FK below can reference note_sections(subject_id, id).
    op.add_column("note_assets", sa.Column("subject_id", sa.UUID(), nullable=True))
    op.execute(
        """
        UPDATE note_assets na
        SET subject_id = ns.subject_id
        FROM note_sections ns
        WHERE ns.id = na.note_section_id
        """
    )
    op.alter_column("note_assets", "subject_id", nullable=False)

    op.create_index(
        "ix_note_assets_subject_section",
        "note_assets",
        ["subject_id", "note_section_id"],
    )
    op.create_foreign_key(
        "fk_note_assets_section",
        "note_assets",
        "note_sections",
        ["subject_id", "note_section_id"],
        ["subject_id", "id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_note_provenance_section",
        "note_provenance",
        "note_sections",
        ["subject_id", "note_section_id"],
        ["subject_id", "id"],
        ondelete="CASCADE",
    )

    op.create_check_constraint(
        "ck_note_assets_asset_type",
        "note_assets",
        f"asset_type IN {ASSET_TYPES}",
    )


def downgrade() -> None:
    op.drop_constraint("ck_note_assets_asset_type", "note_assets", type_="check")
    op.drop_constraint("fk_note_provenance_section", "note_provenance", type_="foreignkey")
    op.drop_constraint("fk_note_assets_section", "note_assets", type_="foreignkey")
    op.drop_index("ix_note_assets_subject_section", table_name="note_assets")
    op.drop_column("note_assets", "subject_id")
    op.execute("ALTER TABLE utterances DROP CONSTRAINT pk_utterances")
    op.execute("ALTER TABLE segments DROP CONSTRAINT pk_segments")
    op.execute("ALTER TABLE note_provenance DROP CONSTRAINT pk_note_provenance")
    op.execute("ALTER TABLE note_sections DROP CONSTRAINT pk_note_sections")
