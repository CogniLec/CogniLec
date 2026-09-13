# S64 — Visual Assembly into Notes
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Attach text diagrams, licensed images, generated illustrations, and OCR'd uploads to the correct note sections. Board photos matched to segments by timestamp proximity or semantic similarity (FR-4.17). Assemble all visual assets into the client note view with proper rendering.

**Component Boundaries:**
- **Allowed:** `src/services/visual_assembly/`, `src/services/visual_assembly/matcher.py`, `src/services/visual_assembly/assembler.py`, `src/services/visual_assembly/renderer.py`, `src/api/routes/notes.py` (attachment endpoints), `tests/test_visual_assembly.py`, `tests/test_asset_matching.py`
- **Off-limits:** Concept detection (S61), image retrieval (S62), image generation (S63), OCR services (S60), upload handling (S59)

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| SQLAlchemy | 2.0.52 | Asset-to-section attachment persistence |
| pgvector | 0.5.0 | Semantic similarity for board photo matching |
| FastAPI | 0.141.1 | Note assembly API |
| pytest | 8.x | Integration tests |
| testcontainers | 4.6.x | PostgreSQL for integration tests |

---

### 2. State Machine & Domain Schemas

**Visual Assembly Flow:**
```
note_sections + visual_assets → match_assets_to_sections
    → for each section:
        → attach text_diagrams
        → attach licensed_images
        → attach generated_images
        → attach ocr_uploads (matched by timestamp/semantic)
    → assembled_note_view (client rendering)
```

**Asset Type Enum:**
```python
# src/services/visual_assembly/models.py
from enum import Enum


class AssetType(str, Enum):
    TEXT_DIAGRAM = "text_diagram"  # Mermaid, KaTeX, etc.
    LICENSED_IMAGE = "licensed_image"  # From S62
    AI_GENERATED = "ai_generated"  # From S63
    OCR_UPLOAD = "ocr_upload"  # From S59/S60
    BOARD_PHOTO = "board_photo"  # Upload with timestamp match
```

**Pydantic Schemas:**
```python
# src/services/visual_assembly/models.py
from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime


class AssetAttachment(BaseModel):
    id: UUID
    note_section_id: UUID
    asset_type: AssetType
    asset_id: UUID  # References note_assets.id
    ordinal: int = 0  # Position within section
    caption: str | None = None
    width: int | None = None
    height: int | None = None
    render_path: str | None = None  # Client render path
    created_at: datetime

    model_config = {"from_attributes": True}


class BoardPhotoMatch(BaseModel):
    upload_id: UUID
    note_section_id: UUID
    match_method: str  # "timestamp" or "semantic"
    match_confidence: float = Field(..., ge=0.0, le=1.0)
    timestamp_delta_seconds: int | None = None  # For timestamp matches
    semantic_similarity: float | None = None  # For semantic matches


class AssembledSection(BaseModel):
    note_section_id: UUID
    heading: str
    body_md: str
    assets: list[AssetAttachment] = Field(default_factory=list)
    board_photos: list[BoardPhotoMatch] = Field(default_factory=list)
    text_diagrams: list[AssetAttachment] = Field(default_factory=list)
    images: list[AssetAttachment] = Field(default_factory=list)
    ocr_text: list[AssetAttachment] = Field(default_factory=list)


class AssembledNoteView(BaseModel):
    session_id: UUID
    subject_id: UUID
    sections: list[AssembledSection]
    total_assets: int
    asset_type_breakdown: dict[str, int]  # asset_type → count


class AssetMatchingConfig(BaseModel):
    timestamp_threshold_seconds: int = 300  # 5 minutes
    semantic_similarity_threshold: float = 0.70
    max_assets_per_section: int = 10
```

**Board Photo Matching (FR-4.17):**
```python
# src/services/visual_assembly/matcher.py
class BoardPhotoMatcher:
    async def match_by_timestamp(
        self,
        upload: UploadRecord,
        segments: list[Segment],
        threshold_seconds: int = 300,
    ) -> BoardPhotoMatch | None:
        """Match board photo to segment by timestamp proximity."""
        # Find segment whose timestamp range overlaps with upload timestamp
        # within threshold_seconds
        ...

    async def match_by_semantic(
        self,
        upload: UploadRecord,
        sections: list[NoteSection],
        threshold: float = 0.70,
    ) -> BoardPhotoMatch | None:
        """Match board photo to note section by semantic similarity."""
        # Compute embedding of upload description
        # Compare with section embeddings using cosine similarity
        # Return match if above threshold
        ...
```

**Attachment Ordering:**
```
Within a note section, assets are ordered by:
1. Ordinal position (explicit ordering)
2. Asset type priority: text_diagrams → images → ocr_uploads → board_photos
3. Creation time (earliest first)
```

**State Transition Rules:**
- Note sections and visual assets exist independently
- Matcher pairs board photos to sections (timestamp or semantic)
- Assembler attaches all asset types to their matched sections
- Renderer produces client-ready `AssembledNoteView`
- Sections with no assets render cleanly (no empty placeholders)

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Create visual assembly Pydantic models | Import succeeds, mypy passes |
| 2 | Create `src/services/visual_assembly/matcher.py` | T64.2: matching accuracy > 0.80 |
| 3 | Create `src/services/visual_assembly/assembler.py` | Assets attached to correct sections |
| 4 | Create `src/services/visual_assembly/renderer.py` | T64.4: all asset types render correctly |
| 5 | Add attachment API endpoints | API returns assembled view |
| 6 | Handle empty sections | T64.5: no empty placeholders |
| 7 | Verify OCR text searchable via S48 | T64.3: OCR'd text incorporated and searchable |
| 8 | Write integration tests | All T64.x tests pass |

**Atomic Sub-tasks:**
1. Visual assembly models and enums
2. Board photo matcher (timestamp + semantic)
3. Asset assembler (attach assets to sections)
4. Client renderer (assembled note view)
5. Attachment API endpoints
6. Empty section handling
7. OCR text integration with search (S48)
8. Integration test suite

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| Board photo matches multiple sections | Use highest confidence match; log warning |
| No match found for board photo | Attach to session-level (not section-specific); log info |
| Asset already attached to section | Skip duplicate attachment; log warning |
| Section has no assets | Render cleanly without empty placeholders |
| OCR text too long for section | Truncate with "..."; log warning |
| Multiple text diagrams for same concept | Use latest; archive older versions |
| Semantic similarity tied | Fall back to timestamp matching |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Pipeline pattern: match → assemble → render
- Strategy pattern: Matching strategy (timestamp vs semantic)
- Composite pattern: `AssembledNoteView` composed of sections with nested assets
- Null object pattern: Empty sections render cleanly (no placeholders)

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase (`BoardPhotoMatcher`, `AssetAssembler`, `NoteRenderer`)
- Files: snake_case (`matcher.py`, `assembler.py`, `renderer.py`)
- Functions: snake_case (`match_by_timestamp`, `assemble_section`, `render_view`)
- Constants: UPPER_SNAKE_CASE

**Code Splitting Metrics:**
- Max function length: 40 lines
- Max file length: 300 lines
- Max class methods: 8

**Type Safety:**
- All function signatures typed with Pydantic v2 models
- `from __future__ import annotations` in all files
- AssetType enum enforced at schema level
- UUID type hints for all ID parameters

---

### 5. API & Interface Contracts

**FastAPI Endpoints:**
```yaml
GET    /api/v1/notes/{session_id}/assembled          → 200 AssembledNoteView
POST   /api/v1/notes/{section_id}/assets/attach      → 201 AssetAttachment
DELETE /api/v1/notes/attachments/{attachment_id}      → 204
GET    /api/v1/notes/{section_id}/assets             → 200 list[AssetAttachment]
PATCH  /api/v1/notes/attachments/{attachment_id}      → 200 AssetAttachment  # reorder
```

**Mock Request/Response Payloads:**
```json
// GET /api/v1/notes/{session_id}/assembled
// Response 200:
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "subject_id": "660e8400-e29b-41d4-a716-446655440001",
  "sections": [
    {
      "note_section_id": "770e8400-e29b-41d4-a716-446655440002",
      "heading": "Gradient Descent",
      "body_md": "Gradient descent is an iterative optimization algorithm...",
      "assets": [
        {
          "id": "aa0e8400-e29b-41d4-a716-446655440005",
          "note_section_id": "770e8400-e29b-41d4-a716-446655440002",
          "asset_type": "text_diagram",
          "asset_id": "bb0e8400-e29b-41d4-a716-446655440006",
          "ordinal": 0,
          "caption": "Gradient descent flowchart",
          "render_path": "/diagrams/770e8400/mermaid_01.svg"
        },
        {
          "id": "cc0e8400-e29b-41d4-a716-446655440007",
          "note_section_id": "770e8400-e29b-41d4-a716-446655440002",
          "asset_type": "licensed_image",
          "asset_id": "dd0e8400-e29b-41d4-a716-446655440008",
          "ordinal": 1,
          "caption": "Convergence visualization",
          "width": 800,
          "height": 600
        }
      ],
      "board_photos": [],
      "text_diagrams": [
        { "id": "aa0e8400...", "asset_type": "text_diagram", "..." : "..." }
      ],
      "images": [
        { "id": "cc0e8400...", "asset_type": "licensed_image", "..." : "..." }
      ],
      "ocr_text": []
    }
  ],
  "total_assets": 2,
  "asset_type_breakdown": {
    "text_diagram": 1,
    "licensed_image": 1
  }
}

// POST /api/v1/notes/{section_id}/assets/attach
// Request:
{
  "asset_type": "board_photo",
  "asset_id": "ee0e8400-e29b-41d4-a716-446655440009",
  "caption": "Board photo from lecture 3"
}

// Response 201:
{
  "id": "ff0e8400-e29b-41d4-a716-446655440010",
  "note_section_id": "770e8400-e29b-41d4-a716-446655440002",
  "asset_type": "board_photo",
  "asset_id": "ee0e8400-e29b-41d4-a716-446655440009",
  "ordinal": 2,
  "caption": "Board photo from lecture 3",
  "created_at": "2026-09-12T10:30:00Z"
}
```

**Database Schema (attachment table):**
```sql
CREATE TABLE note_asset_attachments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    note_section_id UUID NOT NULL,
    subject_id      UUID NOT NULL,
    asset_type      VARCHAR(50) NOT NULL
        CHECK (asset_type IN ('text_diagram', 'licensed_image', 'ai_generated', 'ocr_upload', 'board_photo')),
    asset_id        UUID NOT NULL,
    ordinal         INTEGER NOT NULL DEFAULT 0,
    caption         TEXT,
    width           INTEGER,
    height          INTEGER,
    render_path     VARCHAR(500),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_asset_attachments_section ON note_asset_attachments(note_section_id);
CREATE INDEX idx_asset_attachments_subject ON note_asset_attachments(subject_id);
CREATE UNIQUE INDEX idx_asset_attachments_unique ON note_asset_attachments(note_section_id, asset_id);
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Default |
|----------|------|-------------|---------|
| `DATABASE_URL` | string | PG-MAIN connection | `postgresql+asyncpg://localhost:5432/lis` |
| `BOARD_PHOTO_TIMESTAMP_THRESHOLD` | int | Seconds for timestamp matching | `300` |
| `BOARD_PHOTO_SEMANTIC_THRESHOLD` | float | Cosine similarity for semantic matching | `0.70` |
| `MAX_ASSETS_PER_SECTION` | int | Max visual assets per note section | `10` |
| `DIAGRAM_RENDER_PATH` | string | Path for rendered diagrams | `./rendered_diagrams` |

**Third-Party Integration Contracts:**
- pgvector: Semantic similarity for board photo matching
- FastAPI: Assembly API endpoints
- SQLAlchemy: Asset attachment persistence

**Version Pins:**
- `pgvector` pinned in `pyproject.toml`
- All other deps already pinned in earlier stages

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T64.1 | I | `pytest tests/test_visual_assembly.py::test_board_photo_correct_section -v` | Uploaded board photo appears in correct topic section |
| T64.2 | V | `pytest tests/test_asset_matching.py::test_matching_accuracy -v` | Timestamp/semantic matching accuracy > 0.80 |
| T64.3 | I | `pytest tests/test_visual_assembly.py::test_ocr_text_searchable -v` | OCR'd text incorporated into note content and searchable via S48 |
| T64.4 | E | `pytest tests/test_visual_assembly.py::test_all_render -v` | All asset types render correctly in client |
| T64.5 | I | `pytest tests/test_visual_assembly.py::test_empty_section_clean -v` | Section with no assets renders cleanly |

**Test Case Details (Given/When/Then):**

**T64.1 — Board photo appears in correct topic section**
- **Given:** a session with 3 note sections and 2 board photos uploaded during the session
- **When:** visual assembly runs with timestamp and semantic matching
- **Then:** board photo 1 (timestamp closest to section 2's utterance range) attached to section 2; board photo 2 attached to section 3; `board_photos` list in `AssembledSection` populated correctly

**T64.2 — Matching accuracy > 0.80**
- **Given:** 50 board photos with manually labelled correct sections
- **When:** matcher runs with both timestamp and semantic strategies
- **Then:** overall matching accuracy > 0.80; timestamp matches logged separately from semantic matches; confidence scores reported

**T64.3 — OCR'd text incorporated and searchable**
- **Given:** a board photo with OCR-extracted text "The Krebs cycle produces ATP"
- **When:** visual assembly attaches the OCR'd text to the note section
- **Then:** text appears in note content; searching for "Krebs cycle" via S48 hybrid search returns this section; OCR text is part of the searchable index

**T64.4 — All asset types render correctly in client**
- **Given:** a note section with one of each asset type: text_diagram, licensed_image, ai_generated, ocr_upload, board_photo
- **When:** client renders the assembled note view
- **Then:** each asset type renders with appropriate component: Mermaid diagram rendered, image with attribution displayed, AI-generated badge shown, OCR text displayed as searchable content, board photo shown with timestamp

**T64.5 — Empty section renders cleanly**
- **Given:** a note section with no attached assets
- **When:** client renders the assembled note view
- **Then:** section renders with heading and body_md only; no empty image placeholders; no broken layout; no "No assets" messages

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- Timestamp matching depends on accurate segment timestamps from S09 — if timestamps are wrong, matches will be wrong
- Semantic matching requires embeddings — ensure they're computed and up to date
- Board photos without descriptions may have poor semantic matching — rely on timestamp in that case
- Multiple assets of the same type in one section may cause layout issues — enforce `max_assets_per_section`
- OCR text integration with S48 search requires the text to be in the searchable index — ensure S48 indexing includes OCR text
- Ordinal conflicts when multiple assets are attached simultaneously — use atomic increment

**Fallback Instructions:**
- If timestamp matching fails: fall back to semantic matching; log warning
- If semantic matching fails (no embeddings): fall back to timestamp matching; log warning
- If both fail: attach to session-level; log info
- If rendering fails for an asset type: skip that asset; render others; log warning
- If S48 search unavailable: OCR text still displayed but not searchable; log warning

**Rollback Procedure:**
- Disable visual assembly: feature flag `VISUAL_ASSEMBLY_ENABLED=false`
- Asset attachments are additive — removing them doesn't break notes
- Database migration is additive (new `note_asset_attachments` table)
- Client gracefully handles missing assets

---

### 9. Observability (if applicable)

**Metrics Added:**
- `assembly_sections_processed_total`: counter of sections assembled
- `assembly_assets_attached_total`: counter of assets attached (labels: asset_type)
- `assembly_board_photo_matches_total`: counter of board photo matches (labels: match_method)
- `assembly_matching_accuracy`: gauge of matching accuracy (updated per test run)
- `assembly_empty_sections_total`: counter of sections with no assets
- `assembly_render_latency_seconds`: histogram of assembly rendering time

**Tracing/Logging:**
- Span: `assembly.process` with child spans for `assembly.match`, `assembly.attach`, `assembly.render`
- Log: INFO on assembly with section count, asset count
- Log: INFO on board photo match with upload_id, section_id, method, confidence
- Log: WARN on matching failure with fallback action
- Log: INFO on empty section (normal — not all sections need visuals)

**Alerts:**
- Matching accuracy drops below 0.70: investigate matcher or embeddings
- Board photo match rate < 50%: investigate timestamp quality or semantic embeddings
- Assembly latency > 5s per session: investigate performance

---

### 10. Exit Checklist

- [ ] All tests pass (T64.1–T64.5)
- [ ] Board photo appears in correct topic section (T64.1)
- [ ] Timestamp/semantic matching accuracy > 0.80 (T64.2)
- [ ] OCR'd text incorporated and searchable via S48 (T64.3)
- [ ] All asset types render correctly in client (T64.4)
- [ ] Empty sections render cleanly (T64.5)
- [ ] Asset attachment API endpoints functional
- [ ] Board photo matcher implemented (timestamp + semantic)
- [ ] Asset assembler attaches all asset types to correct sections
