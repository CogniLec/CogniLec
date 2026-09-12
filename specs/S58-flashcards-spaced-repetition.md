# S58 — Flashcards, Spaced Repetition & Export
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Implement flashcard generation per topic with FSRS scheduling for adaptive difficulty, review UI, and export to Markdown, PDF (Typst), DOCX (Pandoc), and Anki (.apkg via genanki).

**Component Boundaries:**
- **Allowed:** `src/services/flashcards/`, `src/services/fsrs/`, `src/services/export/`, `src/api/routes/flashcards.py`, `src/api/routes/export.py`, `tests/test_flashcards.py`, `tests/test_fsrs.py`, `tests/test_export.py`
- **Off-limits:** A5 question generation (S57), RetrievalService (S55), Agent implementations

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| genanki | 0.13.x | Anki .apkg export |
| typst | 0.12.x | PDF export |
| pandoc | 3.x | DOCX export |
| fsrs | 0.4.x | Spaced repetition scheduling |
| Pydantic | 2.13.5 | Output schemas |
| pytest | 8.x | Integration tests |

---

### 2. State Machine & Domain Schemas

**Flashcard Schema:**
```python
# src/services/flashcards/models.py
from pydantic import BaseModel, Field
from uuid import UUID
from enum import Enum

class FlashcardType(str, Enum):
    BASIC = "basic"           # Front/back
    CLOZE = "cloze"           # Fill-in-the-blank
    IMAGE_OCCLUSION = "image" # Image-based (future)

class Flashcard(BaseModel):
    id: UUID
    topic_id: UUID
    front: str = Field(..., max_length=2000)
    back: str = Field(..., max_length=5000)
    card_type: FlashcardType = FlashcardType.BASIC
    source_evidence: str = Field(..., max_length=500)
    difficulty: float = Field(default=0.5, ge=0.0, le=1.0)
    tags: list[str] = Field(default_factory=list)

class FlashcardDeck(BaseModel):
    topic_id: UUID
    topic_name: str
    cards: list[Flashcard]
    total_cards: int = Field(..., ge=0)

class FlashcardGenerationRequest(BaseModel):
    subject_id: UUID
    topic_ids: list[UUID] = Field(default_factory=list)
    cards_per_topic: int = Field(default=10, ge=1, le=50)
    include_cloze: bool = Field(default=True)

# FSRS Scheduling Schema
class ReviewRating(int, Enum):
    """User rating of flashcard review (1-4 scale)."""
    AGAIN = 1   # Complete blackout
    HARD = 2    # Incorrect, but remembered after seeing answer
    GOOD = 3    # Correct with some hesitation
    EASY = 4    # Correct with no hesitation

class ReviewResult(BaseModel):
    flashcard_id: UUID
    rating: ReviewRating
    review_time_ms: int = Field(..., ge=0)
    reviewed_at: datetime

class FSRSState(BaseModel):
    flashcard_id: UUID
    user_id: UUID
    stability: float = Field(default=1.0, ge=0.0)
    difficulty: float = Field(default=0.5, ge=0.0, le=1.0)
    elapsed_days: int = Field(default=0, ge=0)
    scheduled_days: int = Field(default=0, ge=0)
    reps: int = Field(default=0, ge=0)
    lapses: int = Field(default=0, ge=0)
    last_review: datetime | None = None
    next_review: datetime | None = None

class FSRSParameters(BaseModel):
    """FSRS algorithm parameters (default from FSRS-4.5)."""
    request_retention: float = Field(default=0.9, ge=0.0, le=1.0)
    maximum_interval: int = Field(default=365, ge=1)
    w: list[float] = Field(default_factory=lambda: [
        0.4, 0.6, 2.4, 5.8, 4.93, 0.94, 0.86, 0.01, 1.49, 0.14, 0.94, 2.18, 0.05, 0.34, 1.26, 0.29, 2.61
    ])
```

**FSRS Scheduling Flow:**
```
flashcard + rating → FSRS algorithm → new stability/difficulty
                → calculate next_review interval
                → update FSRSState in DB
```

**Export Schema:**
```python
class ExportFormat(str, Enum):
    MARKDOWN = "markdown"
    PDF = "pdf"
    DOCX = "docx"
    ANKI = "anki"

class ExportRequest(BaseModel):
    subject_id: UUID
    topic_ids: list[UUID] = Field(default_factory=list)
    format: ExportFormat
    include_evidence: bool = Field(default=True)
    include_schedule: bool = Field(default=False)  # include review schedule

class ExportResponse(BaseModel):
    file_path: str
    file_size_bytes: int
    format: ExportFormat
    generated_at: datetime
    filename: str
```

**State Transition Rules:**
- Flashcards generated from notes via LLM extraction
- FSRS state initialized on first review
- Review rating updates FSRS state and schedules next review
- Export generates file from flashcard content and metadata

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Create `src/services/flashcards/models.py` with Pydantic schemas | Import succeeds, mypy passes |
| 2 | Create `src/services/fsrs/scheduler.py` with FSRS algorithm | T58.2: FSRS matches reference implementation |
| 3 | Implement flashcard generation from notes | T58.1: valid Q/A pairs generated |
| 4 | Implement review result persistence | T58.3: review results influence scheduling |
| 5 | Implement question selection weighting | T58.4: poorly-performing topics weighted higher |
| 6 | Create `src/services/export/` with Markdown, PDF, DOCX exporters | T58.5: valid files with KaTeX/Mermaid |
| 7 | Create `src/services/export/anki.py` with genanki | T58.6: .apkg imports successfully |
| 8 | Create flashcard and export API endpoints | API returns valid responses |
| 9 | Write integration tests | All T58.x tests pass |

**Atomic Sub-tasks:**
1. Flashcard Pydantic schemas (Flashcard, FlashcardDeck)
2. FSRS scheduler implementation (FSRSState, FSRSParameters)
3. Flashcard generation from notes
4. Review result persistence and scheduling
5. Question selection weighting for poor-performing topics
6. Markdown exporter
7. PDF exporter (Typst)
8. DOCX exporter (Pandoc)
9. Anki exporter (genanki)
10. Flashcard and export API endpoints
11. Integration test suite

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| No notes available for flashcard generation | Return empty deck, log warning |
| FSRS state not found (first review) | Initialize with default parameters |
| Export format not supported | Return 400 with supported formats |
| Typst/Pandoc not installed | Fall back to Markdown export, log warning |
| Anki .apkg generation fails | Return error with details, log exception |
| KaTeX/Mermaid rendering fails in PDF | Include raw syntax, log warning |
| Very large flashcard set (> 1000 cards) | Paginate export, log performance warning |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Service pattern: FlashcardService, FSRSscheduler, ExportService
- Strategy pattern: ExportFormat as strategy for different exporters
- Repository pattern: FlashcardRepository for DB persistence
- Factory pattern: ExportService.create_exporter() for format selection

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase (`FlashcardService`, `FSRSscheduler`, `MarkdownExporter`)
- Files: snake_case (`flashcard_service.py`, `fsrs_scheduler.py`, `markdown_exporter.py`)
- Functions: snake_case (`generate_flashcards`, `schedule_review`, `export_to_pdf`)
- Constants: UPPER_SNAKE_CASE

**Code Splitting Metrics:**
- Max function length: 40 lines
- Max file length: 300 lines
- Max class methods: 8

**Type Safety:**
- All function signatures typed with Pydantic v2 models
- `from __future__ import annotations` in all files
- UUID type hints for all ID parameters
- ReviewRating enum enforced at schema level

---

### 5. API & Interface Contracts

**Flashcard API Endpoints:**
```python
# src/api/routes/flashcards.py
@router.post("/api/v1/flashcards/generate", response_model=FlashcardDeck)
async def generate_flashcards(
    request: FlashcardGenerationRequest,
    current_user: User = Depends(get_current_user),
    flashcard_service: FlashcardService = Depends(get_flashcard_service),
) -> FlashcardDeck:
    """Generate flashcards for topics in a subject."""
    ...

@router.get("/api/v1/flashcards/{topic_id}", response_model=FlashcardDeck)
async def get_flashcards(
    topic_id: UUID,
    current_user: User = Depends(get_current_user),
) -> FlashcardDeck:
    """Get flashcards for a topic."""
    ...

@router.post("/api/v1/flashcards/{flashcard_id}/review", response_model=FSRSState)
async def review_flashcard(
    flashcard_id: UUID,
    rating: ReviewRating,
    current_user: User = Depends(get_current_user),
    fsrs_scheduler: FSRSscheduler = Depends(get_fsrs_scheduler),
) -> FSRSState:
    """Record review result and update schedule."""
    ...

@router.get("/api/v1/flashcards/review/due", response_model=list[Flashcard])
async def get_due_flashcards(
    subject_id: UUID,
    current_user: User = Depends(get_current_user),
) -> list[Flashcard]:
    """Get flashcards due for review."""
    ...
```

**Export API Endpoints:**
```python
# src/api/routes/export.py
@router.post("/api/v1/export", response_model=ExportResponse)
async def export_flashcards(
    request: ExportRequest,
    current_user: User = Depends(get_current_user),
    export_service: ExportService = Depends(get_export_service),
) -> ExportResponse:
    """Export flashcards in specified format."""
    ...

@router.get("/api/v1/export/{export_id}/download")
async def download_export(
    export_id: UUID,
    current_user: User = Depends(get_current_user),
) -> FileResponse:
    """Download exported file."""
    ...
```

**Mock Request/Response Payloads:**
```json
// POST /api/v1/flashcards/generate
// Request:
{
  "subject_id": "550e8400-e29b-41d4-a716-446655440000",
  "topic_ids": ["770e8400-e29b-41d4-a716-446655440002"],
  "cards_per_topic": 10,
  "include_cloze": true
}

// Response 201:
{
  "topic_id": "770e8400-e29b-41d4-a716-446655440002",
  "topic_name": "Gradient Descent",
  "cards": [
    {
      "id": "...",
      "topic_id": "770e8400-e29b-41d4-a716-446655440002",
      "front": "What is the update rule for gradient descent?",
      "back": "θ = θ - α * ∇J(θ), where α is the learning rate and ∇J(θ) is the gradient.",
      "card_type": "basic",
      "source_evidence": "Gradient descent update: θ = θ - α * ∇J(θ)",
      "difficulty": 0.5,
      "tags": ["optimization", "gradient-descent"]
    }
  ],
  "total_cards": 10
}

// POST /api/v1/flashcards/{id}/review
// Request:
{ "rating": 3 }

// Response 200:
{
  "flashcard_id": "...",
  "user_id": "...",
  "stability": 2.5,
  "difficulty": 0.45,
  "elapsed_days": 1,
  "scheduled_days": 3,
  "reps": 2,
  "lapses": 0,
  "last_review": "2026-09-12T10:30:00Z",
  "next_review": "2026-09-15T10:30:00Z"
}

// POST /api/v1/export
// Request:
{
  "subject_id": "550e8400-e29b-41d4-a716-446655440000",
  "topic_ids": [],
  "format": "pdf",
  "include_evidence": true,
  "include_schedule": false
}

// Response 200:
{
  "file_path": "/exports/flashcards_2026-09-12.pdf",
  "file_size_bytes": 1048576,
  "format": "pdf",
  "generated_at": "2026-09-12T10:30:00Z",
  "filename": "flashcards_2026-09-12.pdf"
}
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Default |
|----------|------|-------------|---------|
| `DATABASE_URL` | string | PG-MAIN connection (asyncpg) | `postgresql+asyncpg://localhost:5432/lis` |
| `FSRS_REQUEST_RETENTION` | float | FSRS target retention rate | `0.9` |
| `FSRS_MAXIMUM_INTERVAL` | int | FSRS max review interval (days) | `365` |
| `EXPORT_DIRECTORY` | string | Directory for exported files | `/exports` |
| `TYPST_PATH` | string | Path to typst binary | `typst` |
| `PANDOC_PATH` | string | Path to pandoc binary | `pandoc` |
| `ANKI_MODEL_NAME` | string | Anki note model name | `CogniLec Flashcard` |

**Third-Party Integration Contracts:**
- genanki: Python library for Anki .apkg package generation
- typst: PDF generation with KaTeX math rendering
- pandoc: DOCX generation from Markdown
- FSRS: Spaced repetition scheduling algorithm

**Version Pins:**
- `genanki` pinned in `pyproject.toml`
- `fsrs` pinned in `pyproject.toml`
- `typst` pinned in Docker Compose or system package
- `pandoc` pinned in Docker Compose or system package

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T58.1 | I | `pytest tests/test_flashcards.py::test_flashcards_generated -v` | Flashcards generated with valid Q/A pairs |
| T58.2 | U | `pytest tests/test_fsrs.py::test_fsrs_reference_match -v` | FSRS scheduling correct against reference implementation |
| T58.3 | I | `pytest tests/test_fsrs.py::test_review_results_persist -v` | Review results persisted and influence subsequent scheduling |
| T58.4 | V | `pytest tests/test_flashcards.py::test_topic_weighting -v` | Question selection weights toward poorly-performing topics |
| T58.5 | I | `pytest tests/test_export.py::test_export_formats -v` | Markdown, PDF and DOCX exports produce valid files |
| T58.6 | I | `pytest tests/test_export.py::test_anki_export -v` | Anki .apkg imports successfully into Anki |

**Test Case Details (Given/When/Then):**

**T58.1 — Flashcards generated with valid Q/A pairs**
- **Given:** a topic with 5 note sections covering "Gradient Descent"
- **When:** flashcard generation is called with cards_per_topic=10
- **Then:** 10 flashcards generated, each with valid front/back, source evidence, and topic_id

**T58.2 — FSRS scheduling matches reference implementation**
- **Given:** a flashcard with known review history (3 reviews: Again, Good, Easy)
- **When:** FSRS scheduler processes each review
- **Then:** stability, difficulty, and next_review match the FSRS reference implementation output

**T58.3 — Review results persist and influence scheduling**
- **Given:** a flashcard with FSRS state (stability=1.0, difficulty=0.5)
- **When:** review recorded with rating=3 (Good), then rating=1 (Again)
- **Then:** FSRS state updated; second review increases difficulty and reduces stability

**T58.4 — Topic selection weights toward poor performers**
- **Given:** 3 topics with different review performance (80%, 50%, 90% correct)
- **When:** due flashcards are selected for review
- **Then:** topic with 50% correct rate is weighted higher in selection

**T58.5 — Export formats produce valid files**
- **Given:** a flashcard deck with 10 cards including KaTeX math and Mermaid diagrams
- **When:** export to Markdown, PDF, and DOCX
- **Then:** all three files are valid; PDF renders KaTeX; DOCX is openable

**T58.6 — Anki .apkg imports successfully**
- **Given:** a flashcard deck with 10 cards
- **When:** export to Anki .apkg format
- **Then:** .apkg file is generated; importing into Anki creates 10 cards with correct content

**Verification Commands:**
```bash
# Full local verification
uv run pytest tests/test_flashcards.py tests/test_fsrs.py tests/test_export.py -v -k "S58 or flashcard or fsrs or export" && \
uv run mypy --strict src/services/flashcards/ src/services/fsrs/ src/services/export/ && \
uv run ruff check src/services/flashcards/ src/services/fsrs/ src/services/export/
```

**Exit Criteria:**
- [ ] T58.1 passes — flashcards generated with valid Q/A pairs
- [ ] T58.2 passes — FSRS matches reference implementation
- [ ] T58.3 passes — review results persist and influence scheduling
- [ ] T58.4 passes — question selection weights toward poor performers
- [ ] T58.5 passes — Markdown, PDF, DOCX exports valid
- [ ] T58.6 passes — Anki .apkg imports successfully

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- FSRS reference implementation is critical for correctness — always validate against it
- Typst PDF generation requires KaTeX fonts — ensure they're installed
- Anki .apkg format is version-sensitive — test with current Anki version
- Large flashcard sets (> 1000) may cause export timeout — paginate or stream
- Cloze deletion requires careful text processing — test edge cases

**Fallback Instructions:**
- If Typst unavailable: fall back to Markdown export, log warning
- If Pandoc unavailable: fall back to Markdown export, log warning
- If Anki .apkg fails: return error with details, suggest Markdown export
- If FSRS state corrupted: reset to default parameters, log warning

**Rollback Procedure:**
- Disable flashcard generation: remove from pipeline or feature flag
- FSRS state is additive — removing it doesn't break notes
- Export files are stored in EXPORT_DIRECTORY — can be deleted
- No database migrations required for export removal
- Feature flag: `FLASHCARDS_ENABLED=false` in `.env`

---

### 9. Observability (if applicable)

**Metrics Added:**
- `flashcards_generated_total`: counter of flashcards generated
- `flashcards_reviewed_total`: counter of flashcard reviews (labels: rating)
- `fsrs_scheduled_total`: counter of FSRS scheduling operations
- `export_total`: counter of exports (labels: format)
- `export_latency_seconds`: histogram of export generation time
- `export_file_size_bytes`: histogram of export file sizes

**Tracing/Logging:**
- Span: `flashcards.generate` with child span for LLM extraction
- Span: `fsrs.review` with attributes (rating, new_stability, next_review)
- Span: `export.generate` with attributes (format, file_size)
- Log: INFO on flashcard generation with count and topic
- Log: INFO on review with rating and schedule update
- Log: INFO on export with format and file size

**Alerts:**
- Flashcard generation returns 0 cards: investigate note quality
- Export latency > 30s: check Typst/Pandoc performance
- FSRS scheduling anomaly (next_review in past): investigate algorithm

---

### 10. Exit Checklist

- [ ] All tests pass (T58.1–T58.6)
- [ ] Flashcards generated with valid Q/A pairs
- [ ] FSRS scheduling matches reference implementation
- [ ] Review results persist and influence subsequent scheduling
- [ ] Question selection weights toward poorly-performing topics
- [ ] Markdown, PDF, DOCX exports produce valid files with KaTeX/Mermaid
- [ ] Anki .apkg imports successfully into Anki
- [ ] Flashcard and export API endpoints functional
