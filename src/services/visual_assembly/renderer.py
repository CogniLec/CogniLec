"""S64 — client render-instruction mapping per asset type (T64.4).

There is no browser client in this repo to render into (see docs/gaps.md
gap #2's sibling: no browser client here either), so `render_instruction`
is the server-side contract the client would consume — it is exercised
directly rather than through an actual DOM.
"""

from __future__ import annotations

from src.services.visual_assembly.models import AssetAttachment, AssetType

_COMPONENT_BY_TYPE = {
    AssetType.TEXT_DIAGRAM: "MermaidBlock",
    AssetType.LICENSED_IMAGE: "AttributedImage",
    AssetType.AI_GENERATED: "AIGeneratedImage",
    AssetType.OCR_UPLOAD: "SearchableOCRText",
    AssetType.BOARD_PHOTO: "BoardPhotoWithTimestamp",
}


def render_instruction(attachment: AssetAttachment) -> dict[str, object]:
    component = _COMPONENT_BY_TYPE[attachment.asset_type]
    return {
        "component": component,
        "asset_id": str(attachment.asset_id),
        "caption": attachment.caption,
        "render_path": attachment.render_path,
        "ai_generated_badge": attachment.asset_type == AssetType.AI_GENERATED,
    }
