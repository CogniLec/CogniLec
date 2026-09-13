"""S64 — assembles attached assets into per-section, client-ready views."""

from __future__ import annotations

import uuid

from src.services.visual_assembly.models import (
    _TYPE_ORDER,
    AssembledNoteView,
    AssembledSection,
    AssetAttachment,
    AssetType,
)


def _sort_key(attachment: AssetAttachment) -> tuple[int, int, int]:
    return (attachment.ordinal, _TYPE_ORDER.get(attachment.asset_type, 99), 0)


def assemble_section(
    note_section_id: uuid.UUID,
    heading: str,
    body_md: str,
    attachments: list[AssetAttachment],
) -> AssembledSection:
    """Group attachments by kind; a section with none renders with no placeholders."""
    ordered = sorted(attachments, key=_sort_key)
    return AssembledSection(
        note_section_id=note_section_id,
        heading=heading,
        body_md=body_md,
        assets=ordered,
        text_diagrams=[a for a in ordered if a.asset_type == AssetType.TEXT_DIAGRAM],
        images=[
            a for a in ordered if a.asset_type in (AssetType.LICENSED_IMAGE, AssetType.AI_GENERATED)
        ],
        ocr_text=[a for a in ordered if a.asset_type == AssetType.OCR_UPLOAD],
        board_photos=[],
    )


def assemble_note_view(
    session_id: uuid.UUID,
    subject_id: uuid.UUID,
    sections: list[AssembledSection],
) -> AssembledNoteView:
    total = sum(len(s.assets) for s in sections)
    breakdown: dict[str, int] = {}
    for section in sections:
        for asset in section.assets:
            breakdown[asset.asset_type.value] = breakdown.get(asset.asset_type.value, 0) + 1
    return AssembledNoteView(
        session_id=session_id,
        subject_id=subject_id,
        sections=sections,
        total_assets=total,
        asset_type_breakdown=breakdown,
    )
