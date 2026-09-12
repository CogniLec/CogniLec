# S59 — Post-Session Upload, EXIF Strip & Dedup
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Implement post-session upload UI and API for board photos, handwritten notes, textbook pages, and PDFs, with mandatory EXIF/GPS stripping on ingest, pHash near-duplicate detection, and a re-run trigger that invokes the partial `uploads.ready` path from S47.

**Component Boundaries:**
- **Allowed:** `src/api/routes/uploads.py`, `src/api/schemas/upload.py`, `src/services/uploads/`, `src/services/uploads/exif_strip.py`, `src/services/uploads/dedup.py`, `src/services/uploads/pipeline.py`, `tests/test_uploads.py`, `tests/test_exif_strip.py`, `tests/test_dedup.py`
- **Off-limits:** OCR services (S60), image retrieval (S62), image generation (S63), visual assembly (S64), the full `process_session` flow (S47 — only the partial re-run entrypoint is invoked)

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| Pillow | 11.x | Image EXIF extraction and stripping |
| piexif | 1.1.x | EXIF manipulation fallback |
| imagehash | 4.3.x | Perceptual hashing (pHash) for dedup |
| FastAPI | 0.141.1 | Upload endpoint |
| python-multipart | 0.0.x | Multipart form parsing |
| SQLAlchemy | 2.0.52 | Note assets persistence |
| Alembic | 1.19.2 | Migration for upload tracking columns |
| pytest | 8.x | Integration tests |

---

### 2. State Machine & Domain Schemas

**Upload Processing State Machine:**
```
uploaded → stripping → stripped → dedup_check → unique → ready_for_ocr
                                        ↓
                                   duplicate → merged (existing asset ID returned)
```

**Upload Processing Status Enum:**
```python
# src/services/uploads/models.py
from enum import Enum

class UploadStatus(str, Enum):
    UPLOADED = "uploaded"
    STRIPPING = "stripping"
    STRIPPED = "stripped"
    DEDUP_CHECK = "dedup_check"
    UNIQUE = "unique"
    DUPLICATE = "duplicate"
    READY_FOR_OCR = "ready_for_ocr"
    FAILED = "failed"
```

**Pydantic Schemas:**
```python
# src/api/schemas/upload.py
from pydantic import BaseModel, Field, field_validator
from uuid import UUID
from datetime import datetime
from enum import Enum

class FileType(str, Enum):
    IMAGE = "image"
    PDF = "pdf"
    MULTI_PAGE_PDF = "multi_page_pdf"

class UploadCreate(BaseModel):
    session_id: UUID
    subject_id: UUID
    description: str | None = Field(None, max_length=500)

class UploadResponse(BaseModel):
    id: UUID
    session_id: UUID
    subject_id: UUID
    file_type: FileType
    original_filename: str
    storage_path: str
    status: UploadStatus
    exif_stripped: bool
    phash: str | None = None
    is_duplicate: bool = False
    merged_asset_id: UUID | None = None
    created_at: datetime

    model_config = {"from_attributes": True}

class UploadListResponse(BaseModel):
    items: list[UploadResponse]
    total: int

class UploadConfig(BaseModel):
    max_file_size_bytes: int = 20 * 1024 * 1024  # 20MB
    allowed_image_types: list[str] = ["image/jpeg", "image/png", "image/webp", "image/heic"]
    allowed_pdf_types: list[str] = ["application/pdf"]
    phash_threshold: int = 8  # hamming distance; ≤8 = near-duplicate
```

**SQLAlchemy Model — Upload tracking (added to `note_assets`):**
```sql
-- Migration: add upload tracking columns to note_assets
ALTER TABLE note_assets ADD COLUMN upload_id UUID;
ALTER TABLE note_assets ADD COLUMN original_filename VARCHAR(500);
ALTER TABLE note_assets ADD COLUMN exif_stripped BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE note_assets ADD COLUMN phash VARCHAR(64);
ALTER TABLE note_assets ADD COLUMN source_type VARCHAR(50) NOT NULL DEFAULT 'upload'
    CHECK (source_type IN ('upload', 'web_image', 'generated', 'text_diagram'));
```

**State Transition Rules:**
- `uploaded` → `stripping`: File accepted, EXIF stripping begins immediately
- `stripping` → `stripped`: EXIF/GPS metadata removed; file rewritten to storage
- `stripped` → `dedup_check`: pHash computed and compared against existing hashes
- `dedup_check` → `unique`: No near-duplicate found; proceeds to OCR pipeline
- `dedup_check` → `duplicate`: Near-duplicate found; links to existing `note_assets` record
- `unique` → `ready_for_ocr`: Triggers `uploads.ready` partial re-run (S47)
- Any state → `failed`: Processing error; error recorded, user notified

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Create upload API schema in `src/api/schemas/upload.py` | mypy passes |
| 2 | Create `src/services/uploads/exif_strip.py` — strip EXIF/GPS from images | T59.2: GPS absent from stored objects |
| 3 | Create `src/services/uploads/dedup.py` — pHash computation and comparison | T59.3: duplicate detection works |
| 4 | Create `src/services/uploads/pipeline.py` — orchestrates strip → dedup → trigger | Pipeline runs end-to-end |
| 5 | Create `src/api/routes/uploads.py` — multipart upload endpoint | curl upload succeeds |
| 6 | Add upload tracking columns via Alembic migration | Migration applies cleanly |
| 7 | Wire re-run trigger to S47 `uploads.ready` path | T59.4: partial re-run invoked |
| 8 | Add file type and size validation | T59.5: oversized/unsupported rejected |
| 9 | Write integration tests | All T59.x tests pass |

**Atomic Sub-tasks:**
1. Upload API endpoint with multipart handling
2. EXIF/GPS stripping service
3. pHash dedup service
4. Upload processing pipeline orchestrator
5. S47 `uploads.ready` re-run trigger
6. File validation (type + size)
7. Upload tracking DB migration
8. Integration test suite

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| File exceeds size limit | Reject with 413 and clear message: "File exceeds maximum size of {limit}" |
| Unsupported file type | Reject with 415 and list of supported types |
| EXIF stripping fails (corrupted image) | Store original as-is, log warning, set `exif_stripped=false` |
| pHash computation fails | Skip dedup, treat as unique, log warning |
| Storage backend unavailable | Return 503, retry with exponential backoff |
| S47 re-run trigger fails | Mark upload as `failed`, allow manual retry |
| PDF with zero pages | Reject with 422: "PDF contains no pages" |
| HEIC format not decodable by Pillow | Attempt piexif fallback; if fails, reject with 415 |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Pipeline pattern: upload → strip → dedup → trigger (sequential stages)
- Strategy pattern: EXIF stripping strategy per image type (JPEG vs PNG vs HEIC)
- Repository pattern: UploadRepository for DB persistence

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase (`ExifStripper`, `PhashDedup`, `UploadPipeline`)
- Files: snake_case (`exif_strip.py`, `dedup.py`, `upload_pipeline.py`)
- Functions: snake_case (`strip_exif`, `compute_phash`, `check_duplicate`)
- Constants: UPPER_SNAKE_CASE (`MAX_FILE_SIZE`, `PHASH_THRESHOLD`)

**Code Splitting Metrics:**
- Max function length: 40 lines
- Max file length: 300 lines
- Max class methods: 8

**Type Safety:**
- All function signatures typed with Pydantic v2 models
- `from __future__ import annotations` in all files
- UUID type hints for all ID parameters
- `UploadStatus` enum enforced at schema level

---

### 5. API & Interface Contracts

**FastAPI Endpoints:**
```yaml
POST   /api/v1/uploads                    → 201 UploadResponse
GET    /api/v1/uploads                    → 200 UploadListResponse
GET    /api/v1/uploads/{id}               → 200 UploadResponse
DELETE /api/v1/uploads/{id}               → 204
GET    /api/v1/sessions/{id}/uploads      → 200 UploadListResponse
```

**Mock Request/Response Payloads:**
```json
// POST /api/v1/uploads
// Request: multipart/form-data
// Fields:
//   file: <binary>
//   session_id: "550e8400-e29b-41d4-a716-446655440000"
//   subject_id: "660e8400-e29b-41d4-a716-446655440001"
//   description: "Board photo from today's lecture"

// Response 201:
{
  "id": "770e8400-e29b-41d4-a716-446655440002",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "subject_id": "660e8400-e29b-41d4-a716-446655440001",
  "file_type": "image",
  "original_filename": "board_photo.jpg",
  "storage_path": "uploads/550e8400/770e8400.jpg",
  "status": "ready_for_ocr",
  "exif_stripped": true,
  "phash": "a1b2c3d4e5f6a7b8",
  "is_duplicate": false,
  "merged_asset_id": null,
  "created_at": "2026-09-12T10:30:00Z"
}

// Response 201 (duplicate detected):
{
  "id": "880e8400-e29b-41d4-a716-446655440003",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "subject_id": "660e8400-e29b-41d4-a716-446655440001",
  "file_type": "image",
  "original_filename": "board_photo_v2.jpg",
  "storage_path": "uploads/550e8400/880e8400.jpg",
  "status": "duplicate",
  "exif_stripped": true,
  "phash": "a1b2c3d4e5f6a7b9",
  "is_duplicate": true,
  "merged_asset_id": "770e8400-e29b-41d4-a716-446655440002",
  "created_at": "2026-09-12T10:35:00Z"
}

// POST /api/v1/uploads — Error (413):
{
  "detail": "File exceeds maximum size of 20MB"
}

// POST /api/v1/uploads — Error (415):
{
  "detail": "Unsupported file type 'image/tiff'. Supported: image/jpeg, image/png, image/webp, image/heic, application/pdf"
}
```

**Event/Message Contracts:**
```json
// Event: uploads.ready
{
  "event_type": "uploads.ready",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "upload_ids": ["770e8400-e29b-41d4-a716-446655440002"],
  "timestamp": "2026-09-12T10:30:05Z"
}
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Default |
|----------|------|-------------|---------|
| `DATABASE_URL` | string | PG-MAIN connection | `postgresql+asyncpg://localhost:5432/lis` |
| `UPLOAD_STORAGE_PATH` | string | Local/S3 path for uploaded files | `./uploads` |
| `UPLOAD_MAX_SIZE_MB` | int | Maximum upload file size in MB | `20` |
| `PHASH_HAMMING_THRESHOLD` | int | pHash distance threshold for dedup | `8` |
| `S3_BUCKET` | string | S3 bucket for production storage | `cognilec-uploads` |
| `S3_ENDPOINT_URL` | string | S3 endpoint (MinIO for dev) | `http://localhost:9000` |

**Third-Party Integration Contracts:**
- Pillow: JPEG/PNG/HEIC image decoding and EXIF manipulation
- piexif: Fallback EXIF stripping for JPEG
- imagehash: pHash computation (DCT-based perceptual hash)
- S3/MinIO: Object storage for uploaded files (production)

**Version Pins:**
- `Pillow` pinned in `pyproject.toml`
- `imagehash` pinned in `pyproject.toml`
- `python-multipart` pinned in `pyproject.toml`

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T59.1 | I | `pytest tests/test_uploads.py::test_upload_types -v` | Image, PDF and multi-page uploads accepted |
| T59.2 | S | `pytest tests/test_exif_strip.py::test_gps_absent -v` | GPS and all EXIF metadata absent from stored objects |
| T59.3 | I | `pytest tests/test_dedup.py::test_near_duplicate_merge -v` | Two photos of same board detected as near-duplicates and merged |
| T59.4 | I | `pytest tests/test_uploads.py::test_upload_triggers_rerun -v` | Upload after notes exist triggers partial re-run, not full reprocess |
| T59.5 | I | `pytest tests/test_uploads.py::test_oversized_rejected -v` | Oversized/unsupported file rejected with clear message |

**Test Case Details (Given/When/Then):**

**T59.1 — Image, PDF and multi-page uploads accepted**
- **Given:** a session exists with `status=complete` and `notes_ready=true`
- **When:** user uploads a JPEG image (2MB), a single-page PDF (500KB), and a multi-page PDF (3MB)
- **Then:** all three uploads accepted; each returns `status=ready_for_ocr`; file_type correctly set (`image`, `pdf`, `multi_page_pdf`)

**T59.2 — GPS and EXIF metadata absent from stored objects**
- **Given:** a JPEG image with full EXIF data including GPS coordinates, camera model, and timestamp
- **When:** image is uploaded through the API
- **Then:** stored file has zero EXIF segments; `exif_stripped=true` in response; pHash of stored file differs from original (due to pixel-level changes from stripping); `exiftool` on stored file returns no EXIF data

**T59.3 — Near-duplicate detected and merged**
- **Given:** an existing upload with pHash `a1b2c3d4e5f6a7b8` (a board photo)
- **When:** user uploads a second photo of the same board (slightly different angle, hamming distance ≤ 8)
- **Then:** second upload status is `duplicate`; `is_duplicate=true`; `merged_asset_id` points to the first upload; no new `note_assets` record created

**T59.4 — Upload triggers partial re-run, not full reprocess**
- **Given:** a session with existing notes (`notes_ready=true`) and completed T1–T3 tasks
- **When:** user uploads a new board photo
- **Then:** `uploads.ready` event emitted; S47 partial re-run invoked; T1–T3 cache reused; only the visual enrichment branch re-runs; no full `process_session` triggered

**T59.5 — Oversized/unsupported file rejected**
- **Given:** upload API is configured with 20MB limit
- **When:** user attempts to upload a 25MB TIFF file
- **Then:** API returns 413 with message "File exceeds maximum size of 20MB"; no file written to storage

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- HEIC images from iPhones may not decode in all Pillow versions — test with multiple HEIC variants
- EXIF stripping on PNG removes tEXt chunks — verify this is acceptable or skip PNG EXIF
- pHash threshold too low causes false negatives (missed duplicates); too high causes false positives (merging unrelated images)
- Multi-page PDF page count must be extracted before EXIF stripping (PDFs don't have EXIF, but the pipeline still needs to handle them)
- Re-run trigger must be idempotent — uploading the same file twice should not trigger duplicate re-runs

**Fallback Instructions:**
- If EXIF stripping fails: store original, log warning, set `exif_stripped=false`, continue to dedup
- If pHash computation fails: skip dedup, treat as unique, log warning
- If S47 re-run trigger fails: mark upload as `failed`, allow manual retry via `POST /api/v1/uploads/{id}/retry`
- If storage backend unavailable: return 503 with retry-after header

**Rollback Procedure:**
- Disable uploads: feature flag `UPLOADS_ENABLED=false`
- Uploaded files are in `UPLOAD_STORAGE_PATH` — can be deleted manually
- DB migration is additive (new columns only) — safe to roll back by dropping columns
- Re-run trigger can be disabled independently via `UPLOAD_RERUN_ENABLED=false`

---

### 9. Observability (if applicable)

**Metrics Added:**
- `uploads_total`: counter of uploads (labels: file_type, status)
- `upload_exif_strip_duration_seconds`: histogram of EXIF stripping time
- `upload_dedup_check_duration_seconds`: histogram of dedup check time
- `upload_file_size_bytes`: histogram of upload file sizes
- `upload_duplicates_found_total`: counter of duplicates detected
- `upload_rerun_triggered_total`: counter of S47 re-run triggers

**Tracing/Logging:**
- Span: `upload.process` with child spans for `upload.exif_strip`, `upload.dedup_check`, `upload.rerun_trigger`
- Log: INFO on upload with file_type, file_size, status
- Log: WARN on EXIF stripping failure with error details
- Log: INFO on duplicate detection with source and target asset IDs
- Log: INFO on re-run trigger with session_id and upload_ids

**Alerts:**
- EXIF stripping failure rate > 5%: investigate Pillow/piexif compatibility
- Duplicate detection false positive rate > 10%: adjust pHash threshold
- Re-run trigger failures > 0: investigate S47 partial re-run path

---

### 10. Exit Checklist

- [ ] All tests pass (T59.1–T59.5)
- [ ] EXIF/GPS metadata stripped from all stored images (T59.2)
- [ ] Near-duplicates detected and merged correctly (T59.3)
- [ ] Upload triggers partial re-run, not full reprocess (T59.4)
- [ ] Oversized/unsupported files rejected with clear messages (T59.5)
- [ ] Upload API accepts multipart form data for images and PDFs
- [ ] Upload tracking columns added to `note_assets` table
