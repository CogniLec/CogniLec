# S09 — DB-1 Schema: Utterances & Segments
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Define the `utterances` and `segments` tables with all columns, constraints, HNSW vector indexes per partition, bulk-insert repository, and vector query helpers. Dimension `D=1024` from S06 decision.

**Component Boundaries:**
- **Allowed:** `src/db/models/`, `src/db/repositories/`, migrations, `tests/`
- **Off-limits:** Embedding generation (S25-S26), segmentation algorithm (S28), topic assignment (S30)

**Tech Stack:**
| Tool | Version | Purpose |
|------|---------|---------|
| SQLAlchemy | 2.0.52 | ORM models |
| pgvector | 0.5.0 | vector(1024) columns + HNSW |
| asyncpg | 0.31.0 | Bulk insert |
| EMBEDDING_DIM | 1024 | Frozen in config/models.yaml |

---

### 2. State Machine & Domain Schemas

**`utterances` Table (partitioned by subject_id):**
```sql
CREATE TABLE utterances (
    subject_id    UUID        NOT NULL,
    id            UUID        NOT NULL DEFAULT gen_random_uuid(),
    session_id    UUID        NOT NULL REFERENCES sessions(id),
    seq           INTEGER     NOT NULL,
    start_ms      INTEGER     NOT NULL,
    end_ms        INTEGER     NOT NULL,
    text          TEXT        NOT NULL,
    asr_confidence FLOAT,
    speaker_tag   VARCHAR(10),
    embedding     vector(1024),
    embed_model_ver VARCHAR(50) NOT NULL,
    topic_id      UUID,
    is_relevant   BOOLEAN,            -- NULL = unfiltered (default)
    filter_reason VARCHAR(100),
    outlier_score FLOAT,
    asr_agreement FLOAT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (subject_id, id),
    UNIQUE (subject_id, session_id, seq)
) PARTITION BY LIST (subject_id);
```

**`segments` Table (partitioned by subject_id):**
```sql
CREATE TABLE segments (
    subject_id    UUID        NOT NULL,
    id            UUID        NOT NULL DEFAULT gen_random_uuid(),
    session_id    UUID        NOT NULL REFERENCES sessions(id),
    start_utt     UUID        NOT NULL,
    end_utt       UUID        NOT NULL,
    topic_id      UUID,
    boundary_score FLOAT,
    confidence    FLOAT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (subject_id, id)
) PARTITION BY LIST (subject_id);
```

**SQLAlchemy Models:**
```python
# src/db/models/utterance.py
class Utterance(Base):
    __tablename__ = "utterances"

    subject_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, server_default=text("gen_random_uuid()"))
    session_id: Mapped[UUID] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    asr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    speaker_tag: Mapped[str | None] = mapped_column(String(10), nullable=True)
    embedding = mapped_column(Vector(1024), nullable=True)
    embed_model_ver: Mapped[str] = mapped_column(String(50), nullable=False)
    topic_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    is_relevant: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    filter_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    outlier_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    asr_agreement: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("subject_id", "session_id", "seq", name="uq_utterance_session_seq"),
    )

# src/db/models/segment.py
class Segment(Base):
    __tablename__ = "segments"

    subject_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, server_default=text("gen_random_uuid()"))
    session_id: Mapped[UUID] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    start_utt: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    end_utt: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    topic_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    boundary_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
```

**Pydantic Schemas:**
```python
# src/api/schemas/utterance.py
class UtteranceCreate(BaseModel):
    session_id: UUID
    seq: int = Field(..., ge=0)
    start_ms: int = Field(..., ge=0)
    end_ms: int = Field(..., ge=0)
    text: str = Field(..., min_length=1)
    asr_confidence: float | None = Field(None, ge=0.0, le=1.0)
    speaker_tag: str | None = Field(None, max_length=10)
    embed_model_ver: str = Field(..., min_length=1, max_length=50)

class UtteranceResponse(BaseModel):
    id: UUID
    session_id: UUID
    seq: int
    start_ms: int
    end_ms: int
    text: str
    asr_confidence: float | None
    speaker_tag: str | None
    topic_id: UUID | None
    is_relevant: bool | None
    filter_reason: str | None
    outlier_score: float | None
    asr_agreement: float | None

    model_config = ConfigDict(from_attributes=True)

class SegmentResponse(BaseModel):
    id: UUID
    session_id: UUID
    start_utt: UUID
    end_utt: UUID
    topic_id: UUID | None
    boundary_score: float | None
    confidence: float | None

    model_config = ConfigDict(from_attributes=True)
```

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Create SQLAlchemy models for utterances + segments | Import succeeds |
| 2 | Write migration adding partitioned parent tables | `alembic upgrade head` succeeds |
| 3 | Add HNSW index creation in provisioning (S08) | Index exists after provision |
| 4 | Implement `UtteranceRepository.bulk_insert()` | T09.1 passes |
| 5 | Implement `UtteranceRepository.vector_query()` | T09.3 passes |
| 6 | Add NOT NULL enforcement for `embed_model_ver` | T09.2 passes |
| 7 | Add UNIQUE constraint enforcement | T09.4 passes |
| 8 | Write performance test for vector query | T09.5 passes |
| 9 | Write integration tests | All T09.x pass |

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| Bulk insert with missing `embed_model_ver` | DB NOT NULL constraint rejects; repo raises `IntegrityError` |
| Duplicate `(session_id, seq)` | DB UNIQUE constraint rejects; repo raises `DuplicateKeyError` |
| Vector query returns no results | Return empty list, not error |
| Vector dimension mismatch | pgvector rejects; validate dimension in repository before insert |
| Embedding is NULL | Allow (utterance may not be embedded yet); filter in query |
| 31k vectors query > 200ms | HNSW index must be tuned; check `ef_search` parameter |

---

### 4. Code Style & Architecture Constraints

- **Pattern:** Repository pattern with async methods
- **Bulk insert:** Use `asyncpg.copy_rows()` or SQLAlchemy `exec_driver_sql()` for performance
- **Vector queries:** Use pgvector `<=>` (cosine distance) operator via SQLAlchemy `func.cosine_distance`
- **Embedding dimension:** Hardcoded as `EMBEDDING_DIM = 1024` from `config/models.yaml`
- **is_relevant default:** NULL (unfiltered state); only set by A1 agent (S41)
- **No ORM bulk operations** that bypass per-row validation for critical data

---

### 5. API & Interface Contracts

**Repository Interface:**
```python
# src/db/repositories/utterance_repo.py
class UtteranceRepository:
    async def bulk_insert(self, subject_id: UUID, utterances: list[UtteranceCreate]) -> int:
        """Insert utterances in bulk. Returns count inserted."""

    async def vector_query(
        self, subject_id: UUID, embedding: list[float], k: int = 10,
        session_id: UUID | None = None
    ) -> list[tuple[Utterance, float]]:
        """Find k nearest neighbours by cosine similarity. Returns (utterance, distance) pairs."""

    async def get_by_session(self, subject_id: UUID, session_id: UUID) -> list[Utterance]:
        """Get all utterances for a session, ordered by seq."""

    async def update_topic(self, subject_id: UUID, utterance_id: UUID, topic_id: UUID) -> None:
        """Assign a topic to an utterance."""

    async def update_relevance(
        self, subject_id: UUID, utterance_id: UUID,
        is_relevant: bool, filter_reason: str | None
    ) -> None:
        """Update relevance decision from A1."""

# src/db/repositories/segment_repo.py
class SegmentRepository:
    async def bulk_insert(self, subject_id: UUID, segments: list[SegmentCreate]) -> int:
        """Insert segments in bulk."""

    async def get_by_session(self, subject_id: UUID, session_id: UUID) -> list[Segment]:
        """Get segments for a session, ordered by start_utt sequence."""

    async def update_topic(self, subject_id: UUID, segment_id: UUID, topic_id: UUID) -> None:
        """Assign a topic to a segment."""
```

**Vector Query SQL:**
```sql
SELECT *, embedding <=> $1 AS distance
FROM utterances
WHERE subject_id = $2
  AND embedding IS NOT NULL
  AND ($3::UUID IS NULL OR session_id = $3)
ORDER BY embedding <=> $1
LIMIT $4;
```

---

### 6. Dependency & Environment Configuration

**Required Services:**
- PG-MAIN with pgvector extension (S03)
- Partitions provisioned via S08

**Config Values:**
```python
EMBEDDING_DIM = 1024  # from config/models.yaml
HNSW_M = 16
HNSW_EF_CONSTRUCTION = 64
HNSW_EF_SEARCH = 32
```

---

### 7. Definition of Done & Verification

**Test Matrix:**
| Test ID | Type | Assertion | Command |
|---------|------|-----------|---------|
| T09.1 | I | Bulk insert of 1,000 utterances with embeddings succeeds | `pytest tests/test_utterances.py::test_bulk_insert -v` |
| T09.2 | I | `embed_model_ver` NOT NULL enforced; insert without it fails | `pytest tests/test_utterances.py::test_embed_model_ver_not_null -v` |
| T09.3 | I | Cosine similarity query returns correct nearest neighbours on known fixture | `pytest tests/test_utterances.py::test_vector_query -v` |
| T09.4 | I | `UNIQUE (session_id, seq)` prevents duplicate sequence numbers | `pytest tests/test_utterances.py::test_unique_session_seq -v` |
| T09.5 | P | Vector query over 31k vectors in one partition returns in < 200ms | `pytest tests/test_utterances.py::test_vector_query_performance -v` |
| T09.6 | I | `is_relevant` NULL by default (unfiltered state) | `pytest tests/test_utterances.py::test_is_relevant_default -v` |

**Verification Commands:**
```bash
uv run pytest tests/ -m integration -v -k "utterance or segment" && \
uv run mypy --strict src/db/repositories/ && \
uv run ruff check src/db/repositories/
```

---

### 8. Failure Modes & Self-Correction

| Failure | Detection | Correction |
|---------|-----------|------------|
| Bulk insert too slow | T09.1 timeout | Use `exec_driver_sql()` with `COPY` protocol instead of ORM insert |
| Vector query > 200ms | T09.5 fails | Increase `ef_search`; check HNSW index exists; verify partition pruning |
| Dimension mismatch error | Insert fails | Validate `len(embedding) == EMBEDDING_DIM` before insert |
| Embedding NULL in vector query | Results miss unembedded utterances | Filter `WHERE embedding IS NOT NULL` in query |
| Duplicate seq on retry | T09.4 fails | Use `ON CONFLICT DO NOTHING` for idempotent bulk insert |
| pgvector not installed | Migration fails | Ensure `CREATE EXTENSION vector` ran in init-main.sql |
