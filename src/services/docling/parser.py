"""S51 — syllabus document parsing.

Docling (the spec's named tool) is not installed in this environment and
pulling it in would also require its own transitive OCR/model stack; see
docs/gaps.md gap #9. What is implemented here is genuine, not a stub:

- Text/Markdown: parsed directly with the same regex structure-extraction
  used by A6 (`src.services.syllabus.extraction_agent`) - real logic,
  fully tested.
- PDF: text extracted with `pypdf` (a real dependency, added for this
  block) then run through the same regex extraction. This only works for
  *digital* (non-scanned) PDFs, which is the common case and is the part
  of T51.1 this environment can honestly verify.
- Image (scanned syllabus via OCR): requires Tesseract, a system binary
  not present in this sandbox. `parse_image` raises `OCRUnavailableError`
  rather than fabricating a result; T51.2 is skipped for this reason.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError
from src.api.schemas.syllabus_upload import ParsedSyllabus, ParsedSyllabusItem, UploadFormat
from src.services.syllabus.extraction_agent import (
    ExtractionRejectedError,
    SyllabusExtractionAgent,
    TranscriptChunk,
)


class ParseError(Exception):
    """Document could not be parsed - carries a user-facing message."""


class OCRUnavailableError(ParseError):
    """Scanned/image documents need Tesseract OCR, unavailable in this environment."""


@dataclass
class DoclingConfig:
    ocr_enabled: bool = True
    ocr_language: str = "eng"
    max_pages: int = 100
    table_extraction: bool = True
    image_dpi: int = 300


def detect_format(filename: str, content: bytes) -> UploadFormat:
    lower = filename.lower()
    if lower.endswith(".pdf") or content[:5] == b"%PDF-":
        return UploadFormat.PDF
    if lower.endswith((".png", ".jpg", ".jpeg", ".tif", ".tiff")):
        return UploadFormat.IMAGE
    if lower.endswith((".txt", ".md")):
        return UploadFormat.TEXT
    return UploadFormat.UNKNOWN


class DoclingParser:
    def __init__(self, config: DoclingConfig | None = None) -> None:
        self._config = config or DoclingConfig()
        self._agent = SyllabusExtractionAgent()

    async def parse(self, file_path: Path, fmt: UploadFormat) -> ParsedSyllabus:
        if fmt == UploadFormat.PDF:
            return await self.parse_pdf(file_path)
        if fmt == UploadFormat.IMAGE:
            return await self.parse_image(file_path)
        if fmt == UploadFormat.TEXT:
            return await self.parse_text(file_path.read_text(errors="ignore"))
        msg = "Supported formats: PDF, PNG, JPG, TXT, MD"
        raise ParseError(msg)

    async def parse_pdf(self, file_path: Path) -> ParsedSyllabus:
        try:
            reader = PdfReader(str(file_path))
        except PdfReadError as exc:
            msg = "File appears corrupt. Please re-export from source."
            raise ParseError(msg) from exc

        if len(reader.pages) == 0:
            msg = "Document appears empty."
            raise ParseError(msg)
        if len(reader.pages) > self._config.max_pages:
            msg = f"Document too large. Max {self._config.max_pages} pages."
            raise ParseError(msg)

        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        result = await self.parse_text(text)
        return result.model_copy(update={"total_pages": len(reader.pages)})

    async def parse_image(self, file_path: Path) -> ParsedSyllabus:
        msg = (
            "OCR is unavailable in this environment (Tesseract system binary "
            "not installed) - cannot parse scanned/image syllabi."
        )
        raise OCRUnavailableError(msg)

    async def parse_text(self, content: str) -> ParsedSyllabus:
        try:
            output = await self._agent.extract(
                TranscriptChunk(text=content), subject_id=uuid.uuid4()
            )
        except ExtractionRejectedError as exc:
            msg = "No course structure detected. Ensure the document has clear headings."
            raise ParseError(msg) from exc
        if not output.items:
            msg = "No course structure detected. Ensure the document has clear headings."
            raise ParseError(msg)
        items = [
            ParsedSyllabusItem(
                title=i.title,
                item_type=i.item_type.value,
                ordinal=i.ordinal,
                parent_ordinal=i.parent_ordinal,
                description=i.description,
                weight_pct=i.weight_pct,
                week_number=i.week_number,
                references=i.references,
            )
            for i in output.items
        ]
        return ParsedSyllabus(
            items=items,
            subject_title=output.subject_title,
            parsing_confidence=output.extraction_confidence,
        )
