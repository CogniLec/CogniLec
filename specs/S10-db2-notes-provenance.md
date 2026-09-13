# S10 — DB-2 Schema: Notes, Provenance & Assets
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Define `note_sections`, `note_provenance`, and `note_assets` tables with licence constraint enforced at database level. Notes are the core user-facing output; provenance links notes to source utterances; assets store images/OCR text.

**Component Boundaries:**
- **Allowed:** `src/db/models/`, `src/db/repositories/`, migrations, `tests/`
- **Off-limits:** Note synthesis agent (S44), note API (S46), image retrieval (S62)

**Tech Stack:**
| Tool | Version | Purpose |
|------|---------|---------|
| SQLAlchemy | 2.0.52 | ORM models |
| pgvector | 0.5.0 | vector(1024) for note embeddings |
| Alembic | 1.19.2 | Migration |

---

### 2. State Machine & Domain Schemas

**`note_sections` Table (partitioned by subject_id):**
```sql
CREATE TABLE note_sections (
    subject_id    UUID        NOT NULL,
    id            UUID        NOT NULL DEFAULT gen_random_uuid(),
    topic_id      UUID,
    session_id    UUID,           -- NULL for consolidated notes (FR-7.2)
    heading       TEXT        NOT NULL,
    body_md       TEXT        NOT NULL,
    depth         INTEGER     NOT NULL DEFAULT 0,
    ordinal       INTEGER     NOT NULL,
    embedding     vector(1024),
    model_version VARCHAR(50),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (subject_id, id)
) PARTITION BY LIST (subject_id);
```

**`note_provenance` Table (partitioned by subject_id):**
```sql
CREATE TABLE note_provenance (
    subject_id      UUID    NOT NULL,
    id              UUID    NOT NULL DEFAULT gen_random_uuid(),
    note_section_id UUID    NOT NULL,
    utterance_id    UUID    NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (subject_id, id)
) PARTITION BY LIST (subject_id);
```

**`note_assets` Table (NOT partitioned — cross-subject):**
```sql
CREATE TABLE note_assets (
    id              UUID        NOT NULL DEFAULT gen_random_uuid(),
    note_section_id UUID        NOT NULL,
    asset_type      VARCHAR(50) NOT NULL
        CHECK (asset_type IN ('web_image', 'generated_image', 'board_photo', 'ocr_text', 'diagram')),
    object_key      VARCHAR(500),       -- MinIO key
    source_url      VARCHAR(2000),
    licence         VARCHAR(100),
    match_score     FLOAT,
    is_ai_generated BOOLEAN     NOT NULL DEFAULT FALSE,
    ocr_text        TEXT,
    ocr_confidence  FLOAT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- LICENCE CONSTRAINT (NFR-S7, SRS §9):
    -- source_url and licence NOT NULL when asset_type = 'web_image'
    CONSTRAINT ck_web_image_licence
        CHECK (
            (asset_type != 'web_image') OR
            (source_url IS NOT NULL AND licence IS NOT NULL)
        )
);

-- FK: note_section_id references note_sections(id) via application logic
-- (partitioned table FK not directly supported; enforced at app level)
```

**SQLAlchemy Models:**
```python
# src/db/models/note_section.py
class NoteSection(Base):
    __tablename__ = "note_sections"

    subject_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    topic_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    session_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)  # NULL = consolidated
    heading: Mapped[str] = mapped_column(Text, nullable=False)
    body_md: Mapped[str] = mapped_column(Text, nullable=False)
    depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding = mapped_column(Vector(1024), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


# src/db/models/note_provenance.py
class NoteProvenance(Base):
    __tablename__ = "note_provenance"

    subject_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    note_section_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    utterance_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


# src/db/models/note_asset.py
class AssetType(str, Enum):
    WEB_IMAGE = "web_image"
    GENERATED_IMAGE = "generated_image"
    BOARD_PHOTO = "board_photo"
    OCR_TEXT = "ocr_text"
    DIAGRAM = "diagram"


class NoteAsset(Base):
    __tablename__ = "note_assets"

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    note_section_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    asset_type: Mapped[AssetType] = mapped_column(String(50), nullable=False)
    object_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    licence: Mapped[str | None] = mapped_column(String(100), nullable=True)
    match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_ai_generated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ocr_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
```

**Pydantic Schemas:**
```python
# src/api/schemas/note.py
class NoteSectionCreate(BaseModel):
    topic_id: UUID | None = None
    session_id: UUID | None = None
    heading: str = Field(..., min_length=1)
    body_md: str = Field(..., min_length=1)
    depth: int = Field(0, ge=0, le=10)
    ordinal: int = Field(..., ge=0)


class NoteSectionResponse(BaseModel):
    id: UUID
    topic_id: UUID | None
    session_id: UUID | None
    heading: str
    body_md: str
    depth: int
    ordinal: int
    model_version: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class NoteAssetResponse(BaseModel):
    id: UUID
    asset_type: AssetType
    object_key: str | None
    source_url: str | None
    licence: str | None
    match_score: float | None
    is_ai_generated: bool
    ocr_text: str | None
    ocr_confidence: float | None

    model_config = ConfigDict(from_attributes=True)
```

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Create SQLAlchemy models for note_sections, note_provenance, note_assets | Import succeeds |
| 2 | Write migration for note_sections (partitioned parent table) | Migration applies |
| 3 | Write migration for note_provenance (partitioned parent table) | Migration applies |
| 4 | Write migration for note_assets (non-partitioned) with CHECK constraint | Migration applies |
| 5 | Add licence constraint test | T10.2 passes |
| 6 | Implement NoteSectionRepository | T10.1 passes |
| 7 | Add cascade delete test | T10.3 passes |
| 8 | Add topics centroid test | T10.4 passes |
| 9 | Add asset_type check constraint test | T10.5 passes |

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| web_image without source_url | CHECK constraint rejects at DB level (NFR-S7) |
| web_image without licence | CHECK constraint rejects |
| Deleting note_section with provenance | CASCADE or application-level cleanup (test T10.3) |
| Consolidated notes (session_id=NULL) | Allow; notes without session context |
| Ordinal uniqueness per topic | Application-level enforcement (unique ordinal within topic) |
| asset_type not in allowed list | CHECK constraint rejects (T10.5) |

---

### 4. Code Style & Architecture Constraints

- **Pattern:** Repository pattern with async methods
- **note_assets is NOT partitioned** — it's a global table (images can reference any subject's notes)
- **note_sections and note_provenance ARE partitioned** — subject_id leads PK
- **Consolidated notes:** session_id is NULL; notes span multiple sessions (FR-7.2)
- **Licence constraint:** Enforced at DB level, not just application level
- **Embedding column:** For future retrieval of note sections by semantic similarity
- **Model version:** Tracks which LLM version generated the note

---

### 5. API & Interface Contracts

**Repository Interface:**
```python
# src/db/repositories/note_repo.py
class NoteRepository:
    async def create_section(self, subject_id: UUID, data: NoteSectionCreate) -> NoteSection:
        """Create a note section."""

    async def create_provenance(
        self, subject_id: UUID, note_section_id: UUID, utterance_ids: list[UUID]
    ) -> int:
        """Create provenance links. Returns count created."""

    async def create_asset(self, subject_id: UUID, data: NoteAssetCreate) -> NoteAsset:
        """Create a note asset (image, OCR, diagram)."""

    async def get_sections_by_session(
        self, subject_id: UUID, session_id: UUID
    ) -> list[NoteSection]:
        """Get note sections for a session, ordered by ordinal."""

    async def get_sections_by_topic(self, subject_id: UUID, topic_id: UUID) -> list[NoteSection]:
        """Get consolidated note sections for a topic across all sessions."""

    async def get_assets(self, subject_id: UUID, note_section_id: UUID) -> list[NoteAsset]:
        """Get assets for a note section."""

    async def get_provenance(self, subject_id: UUID, note_section_id: UUID) -> list[NoteProvenance]:
        """Get utterance provenance for a note section."""

    async def delete_section(self, subject_id: UUID, section_id: UUID) -> bool:
        """Delete a note section and cascade to provenance + assets."""
```

---

### 6. Dependency & Environment Configuration

**Required Services:**
- PG-MAIN with pgvector (S03)
- Partitions provisioned via S08
- Object store for assets (S14)

**Config:**
- `EMBEDDING_DIM = 1024` — for note section embeddings

---

### 7. Definition of Done & Verification

**Test Matrix:**
| Test ID | Type | Assertion | Command |
|---------|------|-----------|---------|
| T10.1 | I | Note section with provenance links inserts and reads back | `pytest tests/test_notes.py::test_note_with_provenance -v` |
| T10.2 | I | web_image asset without licence is rejected by constraint (NFR-S7) | `pytest tests/test_notes.py::test_web_image_licence_constraint -v` |
| T10.3 | I | Deleting a note section cascades to provenance and assets | `pytest tests/test_notes.py::test_note_delete_cascade -v` |
| T10.4 | I | topics centroid column stores and retrieves a vector | `pytest tests/test_notes.py::test_note_embedding -v` |
| T10.5 | U | `asset_type` check constraint rejects unknown types | `pytest tests/test_notes.py::test_asset_type_constraint -v` |

**Verification Commands:**
```bash
uv run pytest tests/ -m integration -v -k "note" && \
uv run mypy --strict src/db/models/ && \
uv run ruff check src/db/
```

---

### 8. Failure Modes & Self-Correction

| Failure | Detection | Correction |
|---------|-----------|------------|
| web_image licence constraint not enforced | T10.2 fails | Verify CHECK constraint in migration, not just model |
| Cascade delete doesn't reach assets | T10.3 fails | Ensure application-level cascade (partitioned FK not supported) |
| Consolidated notes missing (session_id=NULL) | Query returns empty | Ensure query allows NULL session_id |
| Ordinal collision within topic | Duplicate ordinal in notes | Add UNIQUE (subject_id, topic_id, ordinal) constraint |
| asset_type check rejects valid type | T10.5 fails | Verify CHECK constraint matches enum values |
| Note embedding dimension wrong | pgvector rejects | Validate len(embedding) == 1024 before insert |
