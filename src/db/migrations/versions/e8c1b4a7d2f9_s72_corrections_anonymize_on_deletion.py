"""S72 follow-up: anonymize corrections on account deletion instead of blocking

Revision ID: e8c1b4a7d2f9
Revises: a7c2e9f4b1d8
Create Date: 2026-09-14

Product decision recorded in `docs/gaps.md` gap #13: a user who has
submitted training corrections must still be deletable. Their corrections
are kept (the training signal is valuable) but anonymized - `user_id` is
nulled rather than the row being blocked or removed.

`corrections_no_update` (migration `c4e7f2a9b6d1`) rejects every UPDATE
outright, and that rule can't simply be relaxed by an `ON DELETE SET NULL`
FK action: Postgres's FK enforcement machinery issues the SET NULL as a
real UPDATE and expects it to take effect, so a rule that silently no-ops
it raises `InternalServerError` rather than nulling the column (see that
migration's docstring). This migration instead narrows the rule so it lets
through only an UPDATE that (a) sets `user_id` and nothing else, and (b)
is explicitly flagged by the caller via a session-local GUC
(`lis.allow_correction_anonymize`). `src/services/account/deletion_service.py`
sets that GUC and nulls `user_id` explicitly, in the same transaction,
before deleting the user row - by the time `DELETE FROM users` runs, no
`corrections` row references that user any more, so the RESTRICT FK never
fires and the FK action itself is left untouched. Every other column stays
provably immutable: the rule's WHERE clause requires them unchanged.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "e8c1b4a7d2f9"
down_revision: str | None = "a7c2e9f4b1d8"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_ANONYMIZE_GUARD = """
    current_setting('lis.allow_correction_anonymize', true) = 'on'
    AND OLD.id = NEW.id
    AND OLD.correction_type IS NOT DISTINCT FROM NEW.correction_type
    AND OLD.subject_id IS NOT DISTINCT FROM NEW.subject_id
    AND OLD.source_id IS NOT DISTINCT FROM NEW.source_id
    AND OLD.original_value IS NOT DISTINCT FROM NEW.original_value
    AND OLD.corrected_value IS NOT DISTINCT FROM NEW.corrected_value
    AND OLD.context IS NOT DISTINCT FROM NEW.context
    AND OLD.consent_for_training IS NOT DISTINCT FROM NEW.consent_for_training
    AND OLD.created_at IS NOT DISTINCT FROM NEW.created_at
    AND NEW.user_id IS NULL
"""


def upgrade() -> None:
    op.execute("DROP RULE IF EXISTS corrections_no_update ON corrections")
    op.execute(
        f"""
        CREATE RULE corrections_no_update AS ON UPDATE TO corrections
        WHERE NOT ({_ANONYMIZE_GUARD})
        DO INSTEAD NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DROP RULE IF EXISTS corrections_no_update ON corrections")
    op.execute("CREATE RULE corrections_no_update AS ON UPDATE TO corrections DO INSTEAD NOTHING")
