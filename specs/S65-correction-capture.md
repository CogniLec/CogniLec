# S65 — Correction Capture & Training Data Pipeline
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Capture every human correction as labelled training data, providing immediate product improvement and durable training examples for model fine-tuning.

**Component Boundaries:**
- **Allowed:** `src/db/models/corrections.py`, `src/db/repositories/correction_repo.py`, `src/api/routes/corrections.py`, `src/api/schemas/corrections.py`, `src/services/correction_capture.py`, `src/services/dataset_export.py`, `src/pipelines/training_data/`, `tests/`
- **Off-limits:** Model training code (S66-S68), ASR models (S68), embedding models (S67), LoRA adapters (S69)

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| Python | 3.12.x | Runtime |
| SQLAlchemy | 2.0.52 | ORM + async |
| Alembic | 1.19.2 | Migrations |
| Pydantic | 2.13.5 | Validation |
| DVC | 3.x | Dataset versioning |
| pandas | 2.2.x | Data manipulation |
| fastapi | 0.141.1 | API framework |

---

### 2. State Machine & Domain Schemas

**Correction Types Enum:**
```
a1_relevance_override | topic_label_edit | split_merge_correction |
syllabus_alignment | image_rejection | note_edit
```

**SQLAlchemy Models:**

```python
# src/db/models/corrections.py
class CorrectionType(str, Enum):
    A1_RELEVANCE_OVERRIDE = "a1_relevance_override"
    TOPIC_LABEL_EDIT = "topic_label_edit"
    SPLIT_MERGE_CORRECTION = "split_merge_correction"
    SYLLABUS_ALIGNMENT = "syllabus_alignment"
    IMAGE_REJECTION = "image_rejection"
    NOTE_EDIT = "note_edit"


class Correction(Base):
    __tablename__ = "corrections"

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    correction_type: Mapped[CorrectionType] = mapped_column(String(50), nullable=False)
    original_prediction: Mapped[dict] = mapped_column(JSONB, nullable=False)
    corrected_value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    context: Mapped[dict] = mapped_column(JSONB, nullable=False)  # utterance_id, topic_id, etc.
    consent_for_training: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )

    __table_args__ = (
        CheckConstraint(
            "correction_type IN ('a1_relevance_override', 'topic_label_edit', 'split_merge_correction', 'syllabus_alignment', 'image_rejection', 'note_edit')",
            name="ck_correction_type",
        ),
    )


class TrainingDataset(Base):
    __tablename__ = "training_datasets"

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    version: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    correction_types: Mapped[list] = mapped_column(JSONB, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    dvc_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
```

**Pydantic Schemas:**

```python
# src/api/schemas/corrections.py
class CorrectionCreate(BaseModel):
    session_id: UUID | None = None
    correction_type: CorrectionType
    original_prediction: dict[str, Any]
    corrected_value: dict[str, Any]
    context: dict[str, Any]  # must contain utterance_id or relevant identifiers
    consent_for_training: bool = True


class CorrectionResponse(BaseModel):
    id: UUID
    user_id: UUID
    session_id: UUID | None
    correction_type: CorrectionType
    original_prediction: dict[str, Any]
    corrected_value: dict[str, Any]
    context: dict[str, Any]
    consent_for_training: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DatasetExportRequest(BaseModel):
    correction_types: list[CorrectionType] | None = None  # None = all types
    min_date: datetime | None = None
    max_date: datetime | None = None
    include_user_ids: list[UUID] | None = None  # explicit consent only


class DatasetExportResponse(BaseModel):
    dataset_id: UUID
    version: str
    row_count: int
    dvc_hash: str
    created_at: datetime
```

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Create Alembic migration for `corrections` and `training_datasets` tables | `alembic upgrade head` succeeds |
| 2 | Create SQLAlchemy models with constraints | DB constraint tests pass |
| 3 | Create Pydantic schemas with validation | mypy passes |
| 4 | Implement CorrectionRepository with append-only semantics | Unit tests pass |
| 5 | Create capture hooks at six correction points | Integration tests pass |
| 6 | Implement dataset export flow with PII scrubbing | T65.3 passes |
| 7 | Integrate DVC for dataset versioning | T65.4 passes |
| 8 | Write integration tests with testcontainers | All T65.x tests pass |

**Atomic Sub-tasks:**
1. Database schema and migration
2. Repository layer with immutable append-only semantics
3. Capture hooks integration with existing services (A1, S31, S32, S52, S63, notes)
4. Dataset export pipeline with PII scrubbing and cross-user leakage prevention
5. DVC integration for versioned datasets

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| Correction without valid context | Validate context contains required identifiers; reject if missing |
| User withdraws consent | Mark correction as `consent_for_training=False`; exclude from future exports |
| Export with no corrections matching filters | Return empty dataset with version increment |
| DVC push fails | Retry with exponential backoff; log failure; dataset remains in local DVC |
| Capture hook called with invalid correction type | Raise ValueError; do not persist |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Repository Pattern: CorrectionRepository with append-only methods
- Event Sourcing: Corrections are immutable events; no updates/deletes
- Pipeline Pattern: Dataset export as composable pipeline stages

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase
- Files: snake_case.py
- Functions: snake_case
- Constants: UPPER_SNAKE_CASE

**Code Splitting Metrics:**
- Max function length: 40 lines
- Max file length: 300 lines
- Repository methods: single responsibility

**Type Safety:**
- All function signatures must have type hints
- Use `from __future__ import annotations` in all model files
- Pydantic models enforce strict validation

---

### 5. API & Interface Contracts

**FastAPI Endpoints:**
```
POST   /api/v1/corrections           → 201 CorrectionResponse
GET    /api/v1/corrections           → 200 list[CorrectionResponse]
GET    /api/v1/corrections/{id}      → 200 CorrectionResponse
POST   /api/v1/corrections/export    → 200 DatasetExportResponse
GET    /api/v1/datasets              → 200 list[DatasetExportResponse]
```

**Request/Response Payloads:**
```json
// POST /api/v1/corrections
// Request:
{
  "session_id": "660e8400-e29b-41d4-a716-446655440001",
  "correction_type": "a1_relevance_override",
  "original_prediction": {"relevant": false, "confidence": 0.85},
  "corrected_value": {"relevant": true},
  "context": {"utterance_id": "770e8400-e29b-41d4-a716-446655440002", "topic_id": "880e8400-e29b-41d4-a716-446655440003"},
  "consent_for_training": true
}
// Response 201:
{
  "id": "990e8400-e29b-41d4-a716-446655440004",
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "session_id": "660e8400-e29b-41d4-a716-446655440001",
  "correction_type": "a1_relevance_override",
  "original_prediction": {"relevant": false, "confidence": 0.85},
  "corrected_value": {"relevant": true},
  "context": {"utterance_id": "770e8400-e29b-41d4-a716-446655440002", "topic_id": "880e8400-e29b-41d4-a716-446655440003"},
  "consent_for_training": true,
  "created_at": "2026-09-12T10:30:00Z"
}

// POST /api/v1/corrections/export
// Request:
{
  "correction_types": ["a1_relevance_override", "topic_label_edit"],
  "min_date": "2026-01-01T00:00:00Z",
  "consent_for_training": true
}
// Response 200:
{
  "dataset_id": "aa0e8400-e29b-41d4-a716-446655440005",
  "version": "v1.2.3",
  "row_count": 1250,
  "dvc_hash": "abc123def456",
  "created_at": "2026-09-12T11:00:00Z"
}
```

**Database Schema (DDL):**
```sql
CREATE TABLE corrections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id UUID REFERENCES sessions(id) ON DELETE SET NULL,
    correction_type VARCHAR(50) NOT NULL
        CHECK (correction_type IN ('a1_relevance_override', 'topic_label_edit', 'split_merge_correction', 'syllabus_alignment', 'image_rejection', 'note_edit')),
    original_prediction JSONB NOT NULL,
    corrected_value JSONB NOT NULL,
    context JSONB NOT NULL,
    consent_for_training BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE training_datasets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version VARCHAR(50) NOT NULL UNIQUE,
    correction_types JSONB NOT NULL,
    row_count INTEGER NOT NULL,
    dvc_hash VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_corrections_user_id ON corrections(user_id);
CREATE INDEX idx_corrections_session_id ON corrections(session_id);
CREATE INDEX idx_corrections_type ON corrections(correction_type);
CREATE INDEX idx_corrections_created_at ON corrections(created_at);
CREATE INDEX idx_corrections_consent ON corrections(consent_for_training) WHERE consent_for_training = TRUE;
```

**Event/Message Contracts:**
```json
{
  "event_type": "correction_captured",
  "correction_id": "990e8400-e29b-41d4-a716-446655440004",
  "correction_type": "a1_relevance_override",
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "session_id": "660e8400-e29b-41d4-a716-446655440001",
  "timestamp": "2026-09-12T10:30:00Z"
}
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Example |
|----------|------|-------------|---------|
| `DATABASE_URL` | string | PG-MAIN connection | `postgresql+asyncpg://localhost:5432/lis` |
| `DVC_REMOTE` | string | DVC remote storage | `s3://lis-training-data` |
| `DVC_S3_ENDPOINT` | string | S3 endpoint for DVC | `https://s3.amazonaws.com` |
| `PII_SCRUBBER_ENABLED` | bool | Enable PII scrubbing in exports | `true` |
| `TRAINING_DATA_CONSENT_DEFAULT` | bool | Default consent for new corrections | `true` |

**Third-Party Integration Contracts:**
- DVC: Version control for training datasets; requires `dvc push` to remote
- S3-compatible storage: Dataset storage backend
- PII Scrubber: `presidio-analyzer` for detecting and scrubbing PII

**Version Pins:**
- DVC: 3.x (latest stable)
- presidio-analyzer: 2.x
- pandas: 2.2.x

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Given | When | Then |
|---------|------|-------|------|------|
| T65.1 | I | Six different correction types exist in the system | Each correction type is captured via API | Each correction is stored with original prediction, corrected value, and context |
| T65.2 | I | A correction is created | Attempt to update or delete the correction | Operation is rejected; correction remains immutable |
| T65.3 | I | Corrections exist with PII in original_prediction or corrected_value | Export dataset is requested | Exported dataset has PII scrubbed and contains no cross-user data leakage |
| T65.4 | I | A dataset export is completed | Export is run again with same parameters | DVC version is incremented; export is reproducible |
| T65.5 | I | User makes a correction to an A1 relevance override | User views the utterance | The utterance now shows the corrected relevance (immediate product improvement) |
| T65.6 | I | User A makes a correction | User B requests a training export | User A's correction is excluded unless User A has consented AND User B has explicit access |

**Verification Commands:**
```bash
# Full local verification
uv run alembic upgrade head && \
uv run alembic downgrade base && \
uv run alembic upgrade head && \
uv run pytest tests/ -m integration -v -k "S65 or correction" && \
uv run mypy --strict src/db/models/corrections.py src/services/correction_capture.py src/services/dataset_export.py && \
uv run ruff check src/db/models/corrections.py src/services/correction_capture.py src/services/dataset_export.py
```

**Exit Criteria:**
- [ ] All six correction types are captured with required fields
- [ ] Corrections are immutable and append-only
- [ ] Export produces PII-free, no cross-user leakage datasets
- [ ] DVC integration provides versioned, reproducible datasets
- [ ] Corrections immediately affect user views (product feature)
- [ ] Consent-based access control works correctly

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- Corrections must be append-only; never allow UPDATE or DELETE on corrections table
- PII scrubbing must run on export, not at capture time (original data needed for context)
- Cross-user leakage prevention requires careful query filtering with consent flags
- DVC push failures can leave local datasets in inconsistent state; need retry logic

**Fallback Instructions:**
- If DVC push fails, retry with exponential backoff (3 attempts); log failure but keep local dataset
- If PII scrubber fails, reject export and log error; do not export unscrubbed data
- If capture hook fails, log error and continue; correction is critical data, must not be lost

**Rollback Procedure:**
- Database migration: `alembic downgrade -1` to remove corrections table
- DVC: revert to previous version with `dvc checkout`
- Feature flag: `ENABLE_CORRECTION_CAPTURE=false` to disable capture hooks

---

### 9. Observability

**Metrics Added:**
- `corrections_captured_total`: Counter by correction_type
- `corrections_exported_total`: Counter by dataset version
- `correction_capture_latency_ms`: Histogram of capture latency
- `dataset_export_duration_seconds`: Histogram of export time
- `pii_scrubber_rejections_total`: Counter of exports rejected due to PII

**Tracing/Logging:**
- Span: `correction.capture` for each correction capture
- Span: `dataset.export` for each export operation
- Log event: `correction_captured` with correction_id, type, user_id
- Log event: `dataset_exported` with dataset_id, version, row_count

**Alerts:**
- Alert if correction capture latency > 500ms (p95)
- Alert if export fails 3 times consecutively
- Alert if PII scrubber rejection rate > 5%

---

### 10. Exit Checklist

- [ ] All tests pass (T65.1, T65.2, T65.3, T65.4, T65.5, T65.6)
- [ ] Corrections table is append-only (no UPDATE/DELETE permissions)
- [ ] Export pipeline scrubs PII and prevents cross-user leakage
- [ ] DVC integration versioned and reproducible
- [ ] Capture hooks integrated at all six correction points
- [ ] Consent-based access control enforced
- [ ] Observability metrics and alerts configured
