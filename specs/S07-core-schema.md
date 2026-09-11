# S07 — Core Schema: Users, Subjects, Sessions
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Initialize Alembic migrations, create the foundational SQLAlchemy 2.0 models (users, subjects, sessions, agent_runs), Pydantic v2 schemas, repository layer with asyncpg, and FastAPI CRUD endpoints for subjects — with all constraints enforced at the database level.

**Component Boundaries:**
- **Allowed:** `migrations/` (Alembic init + first migration), `src/db/models/`, `src/db/repositories/`, `src/api/routes/`, `src/api/schemas/`, `src/api/dependencies/`, `tests/`
- **Off-limits:** Partitioned tables (S08), utterances/segments (S09), notes (S10), syllabus (S11), auth/RLS (S12)

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| Python | 3.12.x | Runtime |
| SQLAlchemy | 2.0.52 | ORM + async |
| asyncpg | 0.31.0 | PG driver |
| Alembic | 1.19.2 | Migrations |
| Pydantic | 2.13.5 | Validation |
| FastAPI | 0.141.1 | API framework |
| pgTAP | via testcontainers | DB constraint testing |
| testcontainers | 4.6.x | Integration test PG |

---

### 2. State Machine & Domain Schemas

**Session Status Enum:**
```
created → recording → transcribed → processing → complete
                                               → failed
```
Transitions enforced in application layer (S23 formalizes this).

**SQLAlchemy Models:**

```python
# src/db/models/user.py
class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(Uuid PrimaryKey, server_default=text("gen_random_uuid()"))
    email: Mapped[str] = mapped_column(Citext, unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

# src/db/models/subject.py
class Subject(Base):
    __tablename__ = "subjects"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, server_default=text("gen_random_uuid()"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_subject_user_name"),)

# src/db/models/session.py
class SessionStatus(str, Enum):
    CREATED = "created"
    RECORDING = "recording"
    TRANSCRIBED = "transcribed"
    PROCESSING = "processing"
    COMPLETE = "complete"
    FAILED = "failed"

class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, server_default=text("gen_random_uuid()"))
    subject_id: Mapped[UUID] = mapped_column(ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False, index=True)
    session_type: Mapped[str] = mapped_column(String(50), nullable=False, default="content")  # content/syllabus/mixed
    status: Mapped[SessionStatus] = mapped_column(String(20), nullable=False, default=SessionStatus.CREATED)
    audio_quality: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes_ready: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

    __table_args__ = (
        CheckConstraint("session_type IN ('content', 'syllabus', 'mixed')", name="ck_session_type"),
        CheckConstraint("status IN ('created', 'recording', 'transcribed', 'processing', 'complete', 'failed')", name="ck_session_status"),
    )

# src/db/models/agent_run.py
class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, server_default=text("gen_random_uuid()"))
    session_id: Mapped[UUID] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_id: Mapped[str] = mapped_column(String(50), nullable=False)  # A1-A6
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    tier: Mapped[int | None] = mapped_column(Integer, nullable=True)  # LLM ladder tier
    prompt_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")  # pending/success/failed
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
```

**Pydantic Schemas:**
```python
# src/api/schemas/subject.py
class SubjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(None, max_length=2000)

class SubjectResponse(BaseModel):
    id: UUID
    name: str
    description: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class SubjectList(BaseModel):
    items: list[SubjectResponse]
    total: int

# src/api/schemas/session.py
class SessionCreate(BaseModel):
    subject_id: UUID
    session_type: Literal["content", "syllabus", "mixed"] = "content"

class SessionResponse(BaseModel):
    id: UUID
    subject_id: UUID
    session_type: str
    status: SessionStatus
    audio_quality: float | None
    notes_ready: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
```

**Repository Pattern:**
```python
# src/db/repositories/subject_repo.py
class SubjectRepository:
    async def create(self, user_id: UUID, data: SubjectCreate) -> Subject
    async def get_by_id(self, subject_id: UUID) -> Subject | None
    async def list_by_user(self, user_id: UUID, offset: int, limit: int) -> tuple[list[Subject], int]
    async def update(self, subject_id: UUID, data: SubjectUpdate) -> Subject | None
    async def delete(self, subject_id: UUID) -> bool

# src/db/repositories/session_repo.py
class SessionRepository:
    async def create(self, subject_id: UUID, session_type: str) -> Session
    async def get_by_id(self, session_id: UUID) -> Session | None
    async def update_status(self, session_id: UUID, new_status: SessionStatus) -> Session
    async def list_by_subject(self, subject_id: UUID, offset: int, limit: int) -> tuple[list[Session], int]
```

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Initialize Alembic: `alembic init -t async src/db/migrations` | `alembic.ini` and `env.py` exist |
| 2 | Configure `alembic.ini` + `env.py` for async SQLAlchemy + PG-MAIN | `alembic current` connects to PG-MAIN |
| 3 | Create `src/db/models/base.py` with declarative base + type exports | Import succeeds |
| 4 | Create `src/db/models/__init__.py` exporting all models | `alembic revision --autogenerate` detects 4 tables |
| 5 | Write first migration (users, subjects, sessions, agent_runs) | `alembic upgrade head` succeeds |
| 6 | Add check constraints + unique constraints to migration | Constraint violations caught by test |
| 7 | Create Pydantic schemas in `src/api/schemas/` | `mypy --strict src/api/schemas/` passes |
| 8 | Create repository layer in `src/db/repositories/` | Unit tests pass |
| 9 | Create FastAPI router in `src/api/routes/subjects.py` | `curl /subjects` returns 200 |
| 10 | Write integration tests with testcontainers | All T07.x tests pass |
| 11 | Verify `alembic downgrade base` leaves clean DB | Downgrade succeeds |

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| Alembic autogenerate misses a change | Ensure all models imported in `__init__.py` |
| Duplicate subject name for same user | DB unique constraint rejects; repo raises `DuplicateKeyError` |
| Session status transition to invalid state | Application-layer guard rejects; DB check constraint as safety net |
| `ON DELETE CASCADE` from subject removes sessions | Test T07.3 verifies; no orphaned sessions |
| Migration fails on existing data | N/A for first migration (empty DB); test with populated DB in S13 |

---

### 4. Code Style & Architecture Constraints

- **Line length:** 100 chars (Ruff)
- **Quotes:** Double (Ruff format)
- **Imports:** `from __future__ import annotations` at top of every model file
- **Naming:** snake_case (vars/functions), PascalCase (classes), UPPER_SNAKE (constants)
- **Type hints:** Required on all function signatures (mypy strict)
- **Model patterns:** Use `Mapped[T]` + `mapped_column()` (SQLAlchemy 2.0 style)
- **Repository pattern:** One repo per aggregate root; methods are `async`; return domain objects not rows
- **Schema separation:** Pydantic schemas in `src/api/schemas/`, SQLAlchemy models in `src/db/models/`
- **Max function length:** 40 lines
- **Max file length:** 300 lines
- **Alembic naming:** `YYYYMMDDHHMMSS_<description>.py` (auto-generated timestamp)
- **No inline SQL** in application code — all through ORM or parameterized queries
- **Conventional Commits:** `feat(db): add core schema migration` etc.

---

### 5. API & Interface Contracts

**FastAPI Endpoints:**
```
POST   /api/v1/subjects          → 201 SubjectResponse
GET    /api/v1/subjects           → 200 SubjectList
GET    /api/v1/subjects/{id}      → 200 SubjectResponse
PATCH  /api/v1/subjects/{id}      → 200 SubjectResponse
DELETE /api/v1/subjects/{id}      → 204

POST   /api/v1/sessions           → 201 SessionResponse
GET    /api/v1/sessions/{id}      → 200 SessionResponse
PATCH  /api/v1/sessions/{id}      → 200 SessionResponse  (status transitions)
GET    /api/v1/subjects/{id}/sessions → 200 list of SessionResponse
```

**Request/Response Payloads:**
```json
// POST /api/v1/subjects
// Request:
{ "name": "Machine Learning", "description": "CS-229 Spring 2026" }
// Response 201:
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "Machine Learning",
  "description": "CS-229 Spring 2026",
  "created_at": "2026-09-12T10:30:00Z"
}

// POST /api/v1/sessions
// Request:
{ "subject_id": "550e8400-e29b-41d4-a716-446655440000", "session_type": "content" }
// Response 201:
{
  "id": "660e8400-e29b-41d4-a716-446655440001",
  "subject_id": "550e8400-e29b-41d4-a716-446655440000",
  "session_type": "content",
  "status": "created",
  "audio_quality": null,
  "notes_ready": false,
  "created_at": "2026-09-12T10:30:00Z"
}

// PATCH /api/v1/sessions/{id}
// Request:
{ "status": "recording" }
// Response 200: (updated session)
```

**Database DDL (first migration):**
```sql
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email CITEXT NOT NULL UNIQUE,
    hashed_password VARCHAR(255) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE subjects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, name)
);

CREATE TABLE sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_id UUID NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    session_type VARCHAR(50) NOT NULL DEFAULT 'content'
        CHECK (session_type IN ('content', 'syllabus', 'mixed')),
    status VARCHAR(20) NOT NULL DEFAULT 'created'
        CHECK (status IN ('created', 'recording', 'transcribed', 'processing', 'complete', 'failed')),
    audio_quality FLOAT,
    notes_ready BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE agent_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    agent_id VARCHAR(50) NOT NULL,
    model VARCHAR(255) NOT NULL,
    tier INTEGER,
    prompt_version VARCHAR(50),
    input_tokens INTEGER,
    output_tokens INTEGER,
    latency_ms INTEGER,
    outcome VARCHAR(20) NOT NULL DEFAULT 'pending',
    error_message TEXT,
    trace_id VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_subjects_user_id ON subjects(user_id);
CREATE INDEX idx_sessions_subject_id ON sessions(subject_id);
CREATE INDEX idx_agent_runs_session_id ON agent_runs(session_id);
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Default |
|----------|------|-------------|---------|
| `DATABASE_URL` | string | PG-MAIN connection (asyncpg) | `postgresql+asyncpg://localhost:5432/lis` |
| `SYLLABUS_DATABASE_URL` | string | PG-SYLLABUS connection | `postgresql+asyncpg://localhost:5432/lis_syllabus` |

**Docker Compose Services Required:**
- `pg-main` (port 5432) — must be running before migration
- `pgbouncer` (port 6432) — optional for tests

**Alembic Configuration (`alembic.ini`):**
```ini
[alembic]
script_location = src/db/migrations
sqlalchemy.url = postgresql+asyncpg://localhost:5432/lis

[loggers]
keys = root,sqlalchemy,alembic
```

**`env.py` Key Config:**
```python
# Use async engine
connectable = create_async_engine(config.get_main_option("sqlalchemy.url"))
# Import all models for autogenerate
target_metadata = Base.metadata
```

---

### 7. Definition of Done & Verification

**Test Matrix:**
| Test ID | Type | Assertion | Command |
|---------|------|-----------|---------|
| T07.1 | I | Subject creation; duplicate name for same user rejected; same name for different user allowed | `pytest tests/test_subjects.py::test_subject_unique_per_user -v` |
| T07.2 | I | Session `status` transitions constrained to declared enum | `pytest tests/test_sessions.py::test_session_status_constraint -v` |
| T07.3 | I | `ON DELETE CASCADE` from subject removes sessions | `pytest tests/test_cascade.py::test_subject_delete_cascades -v` |
| T07.4 | U | Pydantic schema rejects malformed subject payloads | `pytest tests/test_schemas.py::test_subject_validation -v` |
| T07.5 | I | Alembic `upgrade head` then `downgrade base` leaves clean DB | `pytest tests/test_migration.py::test_upgrade_downgrade_roundtrip -v` |

**Verification Commands:**
```bash
# Full local verification
uv run alembic upgrade head && \
uv run alembic downgrade base && \
uv run alembic upgrade head && \
uv run pytest tests/ -m integration -v -k "S07 or subject or session" && \
uv run mypy --strict src/db/ src/api/ && \
uv run ruff check src/db/ src/api/
```

---

### 8. Failure Modes & Self-Correction

| Failure | Detection | Correction |
|---------|-----------|------------|
| Alembic can't connect to PG | `alembic current` fails | Ensure `pg-main` container running: `docker compose up -d pg-main` |
| Autogenerate misses tables | Migration file is empty | Import all models in `src/db/models/__init__.py` |
| Constraint not enforced | Test T07.1/T07.2 fails | Check CHECK constraint syntax; ensure constraint in migration not just model |
| `ON DELETE CASCADE` not working | T07.3 fails | Verify FK has `ondelete="CASCADE"` in model AND migration |
| Ruff/mypy fails on new code | CI red | Run `uv run ruff check --fix src/` and fix type errors |
| Pydantic v2 migration error | Import fails | Use `model_config = ConfigDict(from_attributes=True)` not `orm_mode` |
| Downgrade fails | T07.5 fails | Ensure migration has proper `downgrade()` with `DROP TABLE IF EXISTS` |
