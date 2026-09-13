# S51 — Syllabus Document Upload Path
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Accept syllabus PDF/image/text uploads, extract structure using Docling (+ OCR for scanned documents), feed parsed items to A6, and write to DB-3 — surfaced prominently in the subject-creation flow because syllabus seeding is the highest-leverage cold-start fix (§12.5).

**Component Boundaries:**
- **Allowed:** `src/api/routes/syllabus_upload.py`, `src/services/docling/`, `src/services/syllabus/upload_pipeline.py`, `tests/test_syllabus_upload.py`, `frontend/src/components/SubjectCreation/SyllabusUpload.tsx`
- **Off-limits:** A6 extraction from lecture transcripts (S50), coverage mapping (S52), DB-3 schema (S11), topic-to-syllabus alignment

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| Docling | latest | PDF/structured document parsing |
| Tesseract OCR | 5.x | Scanned image OCR |
| Pillow | 10.x | Image preprocessing for OCR |
| python-multipart | 0.0.9 | File upload handling |
| FastAPI | 0.115.x | Upload endpoint |
| pytest | 8.x | Integration tests |
| testcontainers | 4.6.x | PG-SYLLABUS for tests |

---

### 2. State Machine & Domain Schemas

**Upload Processing Flow:**
```
file_upload → format_detection → docling_parse (or OCR) → structured_items → A6 schema_validation → DB-3_write
                                                                                          ↓ (fail)
                                                                                       user_error_message
```

**Upload State:**
```
UPLOADED → PARSING → EXTRACTING → VALIDATING → WRITING → COMPLETE
            ↓ (OCR needed)      ↓ (parse fail)
         OCR_PROCESSING       FAILED → user_message
```

**Pydantic Models:**
```python
# src/api/schemas/syllabus_upload.py
from pydantic import BaseModel, Field
from enum import Enum


class UploadFormat(str, Enum):
    PDF = "pdf"
    IMAGE = "image"  # PNG, JPG, JPEG, TIFF
    TEXT = "text"  # plain text, markdown
    UNKNOWN = "unknown"


class SyllabusUploadRequest(BaseModel):
    subject_id: UUID
    file: UploadFile  # FastAPI UploadFile
    format_override: UploadFormat | None = None  # auto-detect if None


class SyllabusUploadResponse(BaseModel):
    upload_id: UUID
    status: str  # "processing" | "complete" | "failed"
    items_extracted: int | None = None
    message: str
    error_details: str | None = None


class ParsedSyllabusItem(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    item_type: str = Field(..., pattern="^(module|topic|subtopic|assessment|reference|schedule)$")
    ordinal: int = Field(..., ge=0)
    parent_ordinal: int | None = Field(None, ge=0)
    description: str | None = Field(None, max_length=5000)
    weight_pct: float | None = Field(None, ge=0.0, le=100.0)
    week_number: int | None = Field(None, ge=1)
    references: list[str] = Field(default_factory=list, max_length=20)


class ParsedSyllabus(BaseModel):
    items: list[ParsedSyllabusItem] = Field(..., min_length=1)
    subject_title: str = Field(..., min_length=1, max_length=500)
    total_pages: int | None = None
    parsing_confidence: float = Field(..., ge=0.0, le=1.0)


class DoclingConfig(BaseModel):
    ocr_enabled: bool = True
    ocr_language: str = "eng"
    max_pages: int = 100
    table_extraction: bool = True
    image_dpi: int = 300
```

**State Transition Rules:**
- PDF upload → Docling parses directly, no OCR
- Image upload → OCR preprocessing → Docling parsing
- Text upload → direct parsing, no OCR
- Parse fails → return user-friendly error with suggestions (check file quality)
- Schema validation fails → return error identifying which items failed
- All items validated → write to DB-3 via A6 write path

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Create FastAPI upload endpoint `POST /api/v1/subjects/{subject_id}/syllabus` | Endpoint accepts file upload, returns upload_id |
| 2 | Implement format detection (PDF/image/text) from MIME type and content | Unit test: correct format detected for each type |
| 3 | Integrate Docling for PDF parsing | Integration test: PDF syllabus parsed into items |
| 4 | Add Tesseract OCR for scanned images | Integration test: scanned syllabus parsed via OCR |
| 5 | Implement text/markdown parsing | Unit test: markdown syllabus parsed correctly |
| 6 | Wire parsed output to A6 schema validation | Integration test: parsed items match A6SyllabusOutput |
| 7 | Wire validated items to DB-3 write via A6 write path | Integration test: items land in DB-3 |
| 8 | Add user-facing error messages for common failures | Unit test: malformed doc returns friendly error |
| 9 | Create frontend upload component in subject-creation flow | E2E test: upload appears prominently in onboarding |
| 10 | Run 20-real-syllabi eval | T51.5: parsed items match human reading ≥ 0.85 |

**Atomic Sub-tasks:**
1. FastAPI upload endpoint with file validation
2. Format detection (MIME type + content sniffing)
3. Docling integration for PDF parsing
4. Tesseract OCR for scanned images
5. Text/markdown direct parsing
6. A6 schema validation bridge
7. DB-3 write path integration
8. User-facing error handling and messages
9. Frontend upload component placement
10. Evaluation harness for parsing accuracy

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| Unsupported file format | Return 400 with message: "Supported formats: PDF, PNG, JPG, TXT, MD" |
| Corrupt/unreadable PDF | Return 422 with message: "File appears corrupt. Please re-export from source." |
| Scanned PDF with low DPI | OCR preprocessing with DPI upscaling; if still unreadable, return message |
| Empty document (0 pages) | Return 422 with message: "Document appears empty." |
| Document exceeds max pages (100) | Return 413 with message: "Document too large. Max 100 pages." |
| No syllabus structure found | Return 422 with message: "No course structure detected. Ensure the document has clear headings." |
| File upload timeout (> 60s) | Return 504 with message: "Upload timed out. Try a smaller file." |
| Duplicate upload for same subject | Replace existing items (idempotent upsert by title + parent) |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Strategy pattern: format detection → different parsers (Docling, OCR, text)
- Pipeline pattern: upload → parse → validate → write
- Repository pattern: reuse `SyllabusRepository` from S50 for DB-3 writes
- Error boundary: each stage catches and wraps errors with user-friendly messages

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase (`SyllabusUploadPipeline`, `DoclingParser`)
- Files: snake_case (`syllabus_upload.py`, `docling_parser.py`)
- API paths: kebab-case in URLs, snake_case in payloads
- Error codes: `SYLLABUS_PARSE_001` format

**Code Splitting Metrics:**
- Max function length: 40 lines
- Max file length: 300 lines
- Max class methods: 8

**Type Safety:**
- All function signatures typed with Pydantic v2 models
- `from __future__ import annotations` in all files
- UploadFile type-checked for allowed MIME types

---

### 5. API & Interface Contracts

**Upload Endpoint:**
```yaml
# OpenAPI snippet
/api/v1/subjects/{subject_id}/syllabus:
  post:
    summary: Upload a syllabus document for parsing and DB-3 seeding
    parameters:
      - name: subject_id
        in: path
        required: true
        schema:
          type: string
          format: uuid
    requestBody:
      required: true
      content:
        multipart/form-data:
          schema:
            type: object
            properties:
              file:
                type: string
                format: binary
                description: "Syllabus file (PDF, PNG, JPG, TXT, MD)"
    responses:
      202:
        description: Upload accepted, processing async
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/SyllabusUploadResponse'
      400:
        description: Unsupported format
      413:
        description: File too large
      422:
        description: No syllabus structure detected
```

**Docling Parser Interface:**
```python
# src/services/docling/parser.py
class DoclingParser:
    async def parse_pdf(self, file_path: Path) -> ParsedSyllabus:
        """Parse a PDF syllabus into structured items."""
        ...

    async def parse_image(self, file_path: Path) -> ParsedSyllabus:
        """Parse an image syllabus via OCR → structured items."""
        ...

    async def parse_text(self, content: str) -> ParsedSyllabus:
        """Parse plain text or markdown syllabus into items."""
        ...

    async def parse(self, file_path: Path, fmt: UploadFormat) -> ParsedSyllabus:
        """Route to correct parser based on format."""
        ...
```

**OCR Preprocessing:**
```python
# src/services/docling/ocr.py
class OCRPreprocessor:
    async def preprocess_image(self, image_path: Path) -> Path:
        """Preprocess image for OCR: deskew, enhance contrast, binarize.

        Returns path to preprocessed image suitable for Tesseract.
        """
        ...

    async def extract_text(self, image_path: Path, lang: str = "eng") -> str:
        """Run Tesseract OCR on preprocessed image."""
        ...
```

**Upload Pipeline:**
```python
# src/services/syllabus/upload_pipeline.py
class SyllabusUploadPipeline:
    async def process(self, subject_id: UUID, file: UploadFile) -> SyllabusUploadResponse:
        """Full pipeline: detect format → parse → validate → write to DB-3.

        Uses A6 write-authority context (DB3WriteGuard) for DB-3 writes.
        """
        ...
```

**Frontend Component:**
```tsx
// frontend/src/components/SubjectCreation/SyllabusUpload.tsx
// Placed prominently in the subject-creation flow (§12.5)
// Shows drag-and-drop zone + format guidance
// Progress indicator during parsing
// Success: shows parsed item count with "View Syllabus" link
// Failure: shows error with retry option
```

**Mock Request/Response:**
```json
// POST /api/v1/subjects/550e8400-e29b-41d4-a716-446655440000/syllabus
// Content-Type: multipart/form-data
// Body: file=syllabus.pdf

// Response 202
{
  "upload_id": "660e8400-e29b-41d4-a716-446655440001",
  "status": "processing",
  "items_extracted": null,
  "message": "Syllabus uploaded successfully. Processing..."
}

// Response 200 (after processing)
{
  "upload_id": "660e8400-e29b-41d4-a716-446655440001",
  "status": "complete",
  "items_extracted": 24,
  "message": "Extracted 24 syllabus items. Coverage mapping will begin shortly."
}

// Response 422
{
  "upload_id": "660e8400-e29b-41d4-a716-446655440001",
  "status": "failed",
  "items_extracted": 0,
  "message": "No course structure detected. Ensure the document has clear section headings.",
  "error_details": "Docling found 0 heading elements in document."
}
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Default |
|----------|------|-------------|---------|
| `SYLLABUS_UPLOAD_MAX_SIZE_MB` | int | Max upload file size in MB | `20` |
| `SYLLABUS_UPLOAD_TIMEOUT_S` | int | Upload processing timeout in seconds | `120` |
| `DOCLING_OCR_ENABLED` | bool | Enable OCR for scanned documents | `true` |
| `DOCLING_OCR_LANGUAGE` | string | Tesseract OCR language | `eng` |
| `DOCLING_MAX_PAGES` | int | Max pages to process | `100` |
| `DOCLING_TABLE_EXTRACTION` | bool | Enable table extraction from PDFs | `true` |
| `TESSERACT_CMD` | string | Path to Tesseract binary | `/usr/bin/tesseract` |

**Third-Party Integration Contracts:**
- Docling: PDF parsing library (install via pip, no external API)
- Tesseract OCR: system dependency, must be installed in Docker image
- Pillow: image preprocessing (install via pip)
- A6 write path (S50): reuse `DB3WriteGuard` context for DB-3 writes

**Docker Dependencies:**
```dockerfile
# Must be added to API Dockerfile
RUN apt-get update && apt-get install -y tesseract-ocr tesseract-ocr-eng && rm -rf /var/lib/apt/lists/*
```

**Version Pins:**
- Docling pinned in `pyproject.toml`
- Tesseract 5.x installed via apt
- Pillow pinned in `pyproject.toml`

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T51.1 | I | `pytest tests/test_syllabus_upload.py::test_pdf_syllabus_parsed -v` | PDF syllabus parsed into correct item hierarchy |
| T51.2 | I | `pytest tests/test_syllabus_upload.py::test_scanned_syllabus_ocr -v` | Scanned/photographed syllabus handled via OCR |
| T51.3 | I | `pytest tests/test_syllabus_upload.py::test_malformed_document_fails_gracefully -v` | Malformed document fails gracefully with user-facing message |
| T51.4 | E | `pytest tests/test_syllabus_upload.py::test_upload_in_subject_creation_flow -v` | Upload appears in subject-creation flow, not buried in settings |
| T51.5 | V | `pytest tests/test_syllabus_upload.py::test_parsing_accuracy_20_syllabi -v` | Parsed items match human reading on 20 real syllabi (≥ 0.85) |

**Test Case Details (Given/When/Then):**

**T51.1 — PDF syllabus parsed correctly**
- **Given:** a PDF syllabus with 5 modules, each containing 3–4 topics, with clear headings
- **When:** the PDF is uploaded via `POST /api/v1/subjects/{id}/syllabus`
- **Then:** response contains 15–20 parsed items with correct titles, hierarchy (modules → topics), ordinals, and item_type="module" for top-level, "topic" for children

**T51.2 — Scanned syllabus handled via OCR**
- **Given:** a scanned/photographed syllabus image (PNG, 300 DPI) with visible course structure
- **When:** the image is uploaded via the syllabus upload endpoint
- **Then:** OCR extracts text, Docling parses structure, response contains parsed items with accuracy ≥ 0.80

**T51.3 — Malformed document fails gracefully**
- **Given:** a corrupt PDF file (random bytes, not valid PDF)
- **When:** the file is uploaded
- **Then:** response is HTTP 422 with a user-friendly error message ("File appears corrupt. Please re-export from source."), no server error logged, no partial DB-3 writes

**T51.4 — Upload appears in subject-creation flow**
- **Given:** a user creating a new subject in the frontend
- **When:** they reach the subject-creation page
- **Then:** a prominent "Upload Syllabus" section is visible (not buried in settings), with drag-and-drop zone, format guidance, and progress indicator

**T51.5 — Parsing accuracy ≥ 0.85 on 20 real syllabi**
- **Given:** 20 real syllabus files (10 PDF, 5 scanned images, 5 text/markdown) with human-annotated ground truth
- **When:** each is uploaded and parsed
- **Then:** F1 score (title match + hierarchy + ordinal correctness) ≥ 0.85 across all 20 files, per format type

**Verification Commands:**
```bash
# Full local verification
uv run pytest tests/test_syllabus_upload.py -v -k "S51 or syllabus_upload" && \
uv run mypy --strict src/api/routes/syllabus_upload.py src/services/docling/ && \
uv run ruff check src/api/routes/syllabus_upload.py src/services/docling/ && \
uv run pytest tests/test_syllabus_upload.py::test_parsing_accuracy_20_syllabi -v  # eval gate
```

**Exit Criteria:**
- [ ] T51.1 passes — PDF syllabus parsed into correct hierarchy
- [ ] T51.2 passes — scanned syllabus handled via OCR
- [ ] T51.3 passes — malformed document fails gracefully with user message
- [ ] T51.4 passes — upload appears prominently in subject-creation flow
- [ ] T51.5 passes — parsing accuracy ≥ 0.85 on 20 real syllabi

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- Docling may fail on certain PDF encodings (scanned vs. digital) — always try direct parse first, fall back to OCR
- Tesseract OCR quality depends on image DPI; below 200 DPI produces poor results — upscale images below threshold
- PDFs with complex tables may lose structure during extraction — Docling table extraction helps but is not perfect
- Large PDFs (>50 pages) can cause memory pressure — stream processing or page-by-page chunking may be needed
- The upload endpoint must use A6 write-authority context for DB-3 writes — do NOT bypass `DB3WriteGuard`

**Fallback Instructions:**
- If Docling fails on a PDF: try OCR preprocessing on rendered pages
- If OCR quality is poor: return user message suggesting re-export as text/PDF from source
- If upload processing times out: return 504, log the partial result for debugging
- If DB-3 unavailable during write: cache parsed items in Redis, retry write on next attempt

**Rollback Procedure:**
- Disable syllabus upload by setting `SYLLABUS_UPLOAD_ENABLED=false` in `.env`
- Frontend hides the upload section when feature flag is off
- Existing syllabus items in DB-3 remain untouched
- No database migration rollback needed — upload is additive

---

### 9. Observability

**Metrics Added:**
- `syllabus_upload_total`: counter of upload attempts (labels: format=pdf/image/text, status=success/failed)
- `syllabus_parse_duration_seconds`: histogram of parsing latency by format
- `syllabus_parse_items_count`: histogram of items extracted per upload
- `syllabus_ocr_duration_seconds`: histogram of OCR preprocessing latency
- `syllabus_upload_file_size_bytes`: histogram of uploaded file sizes

**Tracing/Logging:**
- Span: `syllabus.upload` with attributes (subject_id, format, file_size, latency_ms)
- Span: `syllabus.parse` with attributes (format, pages, items_found, parsing_confidence)
- Span: `syllabus.ocr` with attributes (image_dpi, text_length, latency_ms)
- Log: INFO on successful parse with item count and confidence
- Log: WARNING on OCR fallback triggered
- Log: ERROR on parse failure with error details

**Alerts:**
- Upload failure rate > 30% over 1 hour: investigate Docling/OCR configuration
- OCR latency P95 > 30s: check Tesseract performance or image quality

---

### 10. Exit Checklist

- [ ] All tests pass (T51.1, T51.2, T51.3, T51.4, T51.5)
- [ ] Upload endpoint accepts PDF, image, and text files
- [ ] Docling parses digital PDFs correctly
- [ ] Tesseract OCR handles scanned documents
- [ ] Malformed documents produce user-friendly errors
- [ ] Upload is prominently placed in subject-creation flow (§12.5)
- [ ] Parsed items written to DB-3 via A6 write path
- [ ] Parsing accuracy ≥ 0.85 on 20 real syllabi
- [ ] Observability: metrics, traces, and alerts in place
