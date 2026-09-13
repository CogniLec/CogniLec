"""manual-review-app: add 'recall_mismatch' to corrections.correction_type

Revision ID: f1a4c8e2b9d3
Revises: a7c2e9f4b1d8
Create Date: 2026-09-14

The manual-review prototype's quiz/flashcard loop needs a seventh
correction type feeding S65's corrections table: a user reviewing a
flashcard against the real note content and marking their own recall as
wrong. `ck_corrections_type` (migration `c4e7f2a9b6d1`) enumerates the six
existing types explicitly, so a new type needs the constraint replaced
rather than just a new Python enum member.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "f1a4c8e2b9d3"
down_revision: str | None = "a7c2e9f4b1d8"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

OLD_TYPES = (
    "'a1_relevance_override', 'topic_label_edit', 'topic_split_merge', "
    "'syllabus_alignment', 'image_rejection', 'note_edit'"
)
NEW_TYPES = f"{OLD_TYPES}, 'recall_mismatch'"


def upgrade() -> None:
    op.drop_constraint("ck_corrections_type", "corrections", type_="check")
    op.create_check_constraint(
        "ck_corrections_type", "corrections", f"correction_type IN ({NEW_TYPES})"
    )


def downgrade() -> None:
    op.drop_constraint("ck_corrections_type", "corrections", type_="check")
    op.create_check_constraint(
        "ck_corrections_type", "corrections", f"correction_type IN ({OLD_TYPES})"
    )
