"""S59/S60/S63/S64: visual & multimodal tables and columns

Revision ID: b3d6e8f1a4c7
Revises: d3f8a1c9b2e4
Create Date: 2026-09-13

S59 needs upload tracking columns on `note_assets` (upload_id,
original_filename, exif_stripped, phash). `note_assets.asset_type` already
accepts 'upload' and 'board_photo' from S10's check constraint
(f4a1b9c3d7e2), and `source_url`/`licence`/`match_score`/`is_ai_generated`/
`ocr_text`/`ocr_confidence` already exist from S10, so this migration does
not duplicate that column set (the S59/S62/S63 spec drafts assume a bare
S10 schema and re-list them, but they're already present here).

S60 adds `ocr_results` for the dual-model (PaddleOCR/VLM) disagreement
audit trail the spec requires (T60.6) — this is intermediate OCR evidence
distinct from the final `note_assets.ocr_text`/`ocr_confidence` fields.

S63 adds `image_generation_cache` (subject_id, concept_hash) exactly per
spec, backing the FR-4.11 cache-by-concept requirement.

S64 adds `note_asset_attachments`, the section-scoped ordering/caption
layer on top of `note_assets` per spec (assets are content; attachments
are placement).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b3d6e8f1a4c7"
down_revision: str | Sequence[str] | None = "d3f8a1c9b2e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("note_assets", sa.Column("upload_id", sa.UUID(), nullable=True))
    op.add_column(
        "note_assets", sa.Column("original_filename", sa.String(length=500), nullable=True)
    )
    op.add_column(
        "note_assets",
        sa.Column("exif_stripped", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("note_assets", sa.Column("phash", sa.String(length=64), nullable=True))
    op.create_index("ix_note_assets_upload_id", "note_assets", ["upload_id"])

    op.create_table(
        "ocr_results",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("upload_id", sa.UUID(), nullable=False),
        sa.Column("service_used", sa.String(length=50), nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("confidence_level", sa.String(length=20), nullable=False),
        sa.Column("is_low_confidence", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("disagreement_flag", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("paddle_text", sa.Text(), nullable=True),
        sa.Column("vlm_text", sa.Text(), nullable=True),
        sa.Column("paddle_confidence", sa.Float(), nullable=True),
        sa.Column("vlm_confidence", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_ocr_results_upload_id", "ocr_results", ["upload_id"])

    op.create_table(
        "image_generation_cache",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("subject_id", sa.UUID(), nullable=False),
        sa.Column("concept_hash", sa.String(length=64), nullable=False),
        sa.Column("generated_image_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("subject_id", "concept_hash", name="uq_image_gen_cache_subject_hash"),
    )
    op.create_index("ix_image_gen_cache_subject", "image_generation_cache", ["subject_id"])

    op.create_table(
        "note_asset_attachments",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("note_section_id", sa.UUID(), nullable=False),
        sa.Column("subject_id", sa.UUID(), nullable=False),
        sa.Column("asset_type", sa.String(length=50), nullable=False),
        sa.Column("asset_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("render_path", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "asset_type IN ('text_diagram', 'licensed_image', 'ai_generated', "
            "'ocr_upload', 'board_photo')",
            name="ck_note_asset_attachments_type",
        ),
        sa.UniqueConstraint(
            "note_section_id", "asset_id", name="uq_note_asset_attachments_section_asset"
        ),
    )
    op.create_index("ix_asset_attachments_section", "note_asset_attachments", ["note_section_id"])
    op.create_index("ix_asset_attachments_subject", "note_asset_attachments", ["subject_id"])


def downgrade() -> None:
    op.drop_table("note_asset_attachments")
    op.drop_table("image_generation_cache")
    op.drop_table("ocr_results")
    op.drop_index("ix_note_assets_upload_id", table_name="note_assets")
    op.drop_column("note_assets", "phash")
    op.drop_column("note_assets", "exif_stripped")
    op.drop_column("note_assets", "original_filename")
    op.drop_column("note_assets", "upload_id")
