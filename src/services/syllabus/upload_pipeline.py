"""S51 — syllabus document upload pipeline: detect -> parse -> validate -> write."""

from __future__ import annotations

import uuid
from pathlib import Path

from config.schemas.a6_syllabus import A6SyllabusOutput, ExtractedSyllabusItem, ItemType
from src.api.schemas.syllabus_upload import ParsedSyllabus, SyllabusUploadResponse, UploadFormat
from src.db.repositories.syllabus_repo import SyllabusRepository
from src.db.write_guard import DB3WriteGuard
from src.services.docling.parser import DoclingParser, ParseError, detect_format


def _parsed_to_extraction_output(parsed: ParsedSyllabus) -> A6SyllabusOutput:
    items = [
        ExtractedSyllabusItem(
            title=i.title,
            item_type=ItemType(i.item_type),
            ordinal=i.ordinal,
            parent_ordinal=i.parent_ordinal,
            description=i.description,
            weight_pct=i.weight_pct,
            week_number=i.week_number,
            references=i.references,
        )
        for i in parsed.items
    ]
    return A6SyllabusOutput(
        items=items,
        subject_title=parsed.subject_title,
        extraction_confidence=parsed.parsing_confidence,
        grade_of_authority=1 if parsed.parsing_confidence >= 0.85 else 2,
    )


class SyllabusUploadPipeline:
    def __init__(self, repo: SyllabusRepository, parser: DoclingParser | None = None) -> None:
        self._repo = repo
        self._parser = parser or DoclingParser()

    async def process(
        self,
        subject_id: uuid.UUID,
        file_path: Path,
        filename: str,
    ) -> SyllabusUploadResponse:
        """Full pipeline: detect format -> parse -> validate -> write to DB-3."""
        upload_id = uuid.uuid4()
        content = file_path.read_bytes()
        fmt = detect_format(filename, content)
        if fmt == UploadFormat.UNKNOWN:
            return SyllabusUploadResponse(
                upload_id=upload_id,
                status="failed",
                items_extracted=0,
                message="Supported formats: PDF, PNG, JPG, TXT, MD",
                error_details="Unrecognised file extension/content.",
            )

        try:
            parsed = await self._parser.parse(file_path, fmt)
        except ParseError as exc:
            return SyllabusUploadResponse(
                upload_id=upload_id,
                status="failed",
                items_extracted=0,
                message=str(exc),
                error_details=str(exc),
            )

        output = _parsed_to_extraction_output(parsed)
        with DB3WriteGuard.a6_write_context():
            created = await self._repo.bulk_create_items(subject_id, output.items, source="upload")

        return SyllabusUploadResponse(
            upload_id=upload_id,
            status="complete",
            items_extracted=len(created),
            message=(
                f"Extracted {len(created)} syllabus items. Coverage mapping will begin shortly."
            ),
        )
