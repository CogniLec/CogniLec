"""S59 — upload persistence into `note_assets` (upload tracking columns)."""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.services.uploads.models import FileType, UploadStatus


class UploadRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_phashes_for_subject(self, subject_id: uuid.UUID) -> list[tuple[str, str]]:
        result = await self._session.execute(
            text(
                "SELECT id, phash FROM note_assets "
                "WHERE subject_id = :subject_id AND phash IS NOT NULL"
            ),
            {"subject_id": subject_id},
        )
        return [(str(row[0]), row[1]) for row in result.fetchall()]

    async def create_upload(
        self,
        *,
        session_id: uuid.UUID,
        subject_id: uuid.UUID,
        file_type: FileType,
        original_filename: str,
        stored_bytes: bytes,
        status: UploadStatus,
        exif_stripped: bool,
        phash: str | None,
        merged_asset_id: uuid.UUID | None,
    ) -> dict[str, object]:
        upload_id = uuid.uuid4()
        note_section_id = await self._session.scalar(
            text("SELECT id FROM note_sections WHERE subject_id = :sid LIMIT 1"),
            {"sid": subject_id},
        )
        asset_type = "board_photo" if status == UploadStatus.DUPLICATE else "upload"
        object_key = f"uploads/{session_id}/{upload_id}"
        row = (
            await self._session.execute(
                text(
                    """
                    INSERT INTO note_assets (
                        subject_id, note_section_id, asset_type, object_key,
                        upload_id, original_filename, exif_stripped, phash,
                        is_ai_generated
                    ) VALUES (
                        :subject_id, :note_section_id, :asset_type, :object_key,
                        :upload_id, :original_filename, :exif_stripped, :phash,
                        false
                    )
                    RETURNING id, created_at
                    """
                ),
                {
                    "subject_id": subject_id,
                    "note_section_id": note_section_id,
                    "asset_type": asset_type,
                    "object_key": object_key,
                    "upload_id": upload_id,
                    "original_filename": original_filename,
                    "exif_stripped": exif_stripped,
                    "phash": phash,
                },
            )
        ).fetchone()
        await self._session.flush()
        assert row is not None
        return {
            "id": row[0],
            "session_id": session_id,
            "subject_id": subject_id,
            "file_type": file_type,
            "original_filename": original_filename,
            "storage_path": object_key,
            "status": status,
            "exif_stripped": exif_stripped,
            "phash": phash,
            "is_duplicate": status == UploadStatus.DUPLICATE,
            "merged_asset_id": merged_asset_id,
            "created_at": row[1],
        }
