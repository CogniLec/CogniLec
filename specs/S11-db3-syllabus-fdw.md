# S11 — DB-3: Syllabus Instance & FDW Link
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Create the syllabus schema on the **separate** PG-SYLLABUS instance, install `postgres_fdw` on PG-MAIN, create server + user mapping + foreign table so PG-MAIN can read syllabus items joined to local subjects. Register both in pgAdmin.

**Component Boundaries:**
- **Allowed:** `src/db/models/`, `src/db/repositories/`, migrations on both PG instances, `tests/`
- **Off-limits:** Syllabus extraction agent (S50), coverage mapping (S52), topic-to-syllabus alignment

**Tech Stack:**
| Tool | Version | Purpose |
|------|---------|---------|
| PostgreSQL | 17 | Separate instances |
| postgres_fdw | (built-in) | Cross-instance queries |
| SQLAlchemy | 2.0.52 | ORM models |
| Alembic | 1.19.2 | Migrations on both instances |

---

### 2. State Machine & Domain Schemas

**PG-SYLLABUS Schema (`lis_syllabus`):**
```sql
CREATE TABLE syllabus_items (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_id          UUID NOT NULL,          -- references local subjects via FDW
    parent_id           UUID REFERENCES syllabus_items(id) ON DELETE SET NULL,
    ordinal             INTEGER NOT NULL,
    title               TEXT NOT NULL,
    description         TEXT,
    embedding           vector(1024),
    source              VARCHAR(50) NOT NULL DEFAULT 'lecture'
        CHECK (source IN ('lecture', 'upload', 'manual')),
    source_session_id   UUID,                   -- NULL if from upload/manual
    coverage_status     VARCHAR(20) NOT NULL DEFAULT 'not_started'
        CHECK (coverage_status IN ('not_started', 'partial', 'covered')),
    covered_by          UUID[] DEFAULT '{}',     -- array of topic_ids
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_syllabus_subject ON syllabus_items(subject_id);
CREATE INDEX idx_syllabus_parent ON syllabus_items(parent_id);
```

**FDW Setup (on PG-MAIN):**
```sql
-- Install FDW extension
CREATE EXTENSION IF NOT EXISTS postgres_fdw;

-- Create server connection to PG-SYLLABUS
CREATE SERVER syllabus_server
    FOREIGN DATA WRAPPER postgres_fdw
    OPTIONS (host 'pg-syllabus', port '5432', dbname 'lis_syllabus');

-- Create user mapping (read-only from PG-MAIN's perspective)
CREATE USER MAPPING FOR lis
    SERVER syllabus_server
    OPTIONS (user 'lis', password '/* from .env */');

-- Import foreign schema (public schema from PG-SYLLABUS)
IMPORT FOREIGN SCHEMA public
    LIMIT TO (syllabus_items)
    FROM SERVER syllabus_server
    INTO public;

-- Grant read-only access to the foreign table
GRANT SELECT ON FOREIGN TABLE syllabus_items TO lis;
```

**SQLAlchemy Model:**
```python
# src/db/models/syllabus_item.py
class SyllabusItem(Base):
    __tablename__ = "syllabus_items"

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    subject_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    parent_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("syllabus_items.id", ondelete="SET NULL"), nullable=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding = mapped_column(Vector(1024), nullable=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="lecture")
    source_session_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    coverage_status: Mapped[str] = mapped_column(String(20), nullable=False, default="not_started")
    covered_by: Mapped[list[UUID]] = mapped_column(ARRAY(Uuid), nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
```

**Pydantic Schemas:**
```python
# src/api/schemas/syllabus.py
class SyllabusItemCreate(BaseModel):
    parent_id: UUID | None = None
    ordinal: int = Field(..., ge=0)
    title: str = Field(..., min_length=1, max_length=500)
    description: str | None = Field(None, max_length=5000)
    source: Literal["lecture", "upload", "manual"] = "lecture"
    source_session_id: UUID | None = None


class SyllabusItemResponse(BaseModel):
    id: UUID
    subject_id: UUID
    parent_id: UUID | None
    ordinal: int
    title: str
    description: str | None
    source: str
    source_session_id: UUID | None
    coverage_status: str
    covered_by: list[UUID]

    model_config = ConfigDict(from_attributes=True)


class SyllabusTree(BaseModel):
    items: list[SyllabusItemResponse]
    hierarchy: dict[UUID, list[UUID]]  # parent_id -> [child_ids]
```

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Create migration for PG-SYLLABUS: syllabus_items table | `alembic -x dbname=lis_syllabus upgrade head` succeeds |
| 2 | Install postgres_fdw on PG-MAIN | `CREATE EXTENSION postgres_fdw` succeeds |
| 3 | Create FDW server + user mapping on PG-MAIN | FDW connection works |
| 4 | Import foreign schema from PG-SYLLABUS | `SELECT * FROM syllabus_items` returns rows |
| 5 | Create read-through repository | T11.1-T11.3 pass |
| 6 | Test FDW failure handling | T11.4 passes |
| 7 | Test read-only enforcement | T11.5 passes |
| 8 | Register both servers in pgAdmin servers.json | pgAdmin shows both |

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| PG-SYLLABUS unavailable | FDW query fails with handled error; application returns empty/error, not hang |
| FDW user has write permissions | T11.5 fails; revoke INSERT/UPDATE/DELETE on foreign table |
| Hierarchy cycle (parent_id loop) | Application-level guard prevents circular references |
| Foreign table out of sync | FDW reads live; no caching needed |
| Password in user mapping exposed | Use SOPS-encrypted secrets; never commit plaintext |
| FDW join performance | Ensure subject_id indexed on both sides |

---

### 4. Code Style & Architecture Constraints

- **Pattern:** Read-through repository (no caching; FDW reads are live)
- **Separate Alembic configs:** `alembic.ini` for PG-MAIN; `-x dbname=lis_syllabus` for PG-SYLLABUS
- **User mapping:** FDW user `lis` has SELECT-only on foreign table
- **Hierarchy:** Self-referential FK (`parent_id → id`); max depth enforced in application
- **Coverage status:** Updated by S52; not set during initial extraction
- **covered_by array:** Updated when topics align to syllabus items (S52)

---

### 5. API & Interface Contracts

**Repository Interface:**
```python
# src/db/repositories/syllabus_repo.py
class SyllabusRepository:
    async def create_item(self, subject_id: UUID, data: SyllabusItemCreate) -> SyllabusItem:
        """Create a syllabus item on PG-SYLLABUS."""

    async def get_tree(self, subject_id: UUID) -> SyllabusTree:
        """Get full syllabus tree for a subject."""

    async def get_item(self, item_id: UUID) -> SyllabusItem | None:
        """Get a single syllabus item."""

    async def update_coverage(
        self, item_id: UUID, status: str, topic_ids: list[UUID]
    ) -> SyllabusItem:
        """Update coverage status and linked topic IDs."""

    async def delete_item(self, item_id: UUID) -> bool:
        """Delete a syllabus item and its children."""
```

**FDW Query Pattern:**
```sql
-- From PG-MAIN, join local subjects with foreign syllabus_items
SELECT s.id as subject_id, si.*
FROM subjects s
JOIN syllabus_items si ON si.subject_id = s.id
WHERE s.id = $1
ORDER BY si.ordinal;
```

---

### 6. Dependency & Environment Configuration

**Required Services:**
- PG-MAIN (port 5432) — FDW client
- PG-SYLLABUS (port 5433) — FDW server
- Both in docker-compose (S03)

**Environment Variables:**
| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PG-MAIN connection |
| `SYLLABUS_DATABASE_URL` | PG-SYLLABUS direct connection |
| `POSTGRES_PASSWORD` | Used in FDW user mapping |

**FDW Configuration:**
```python
# src/db/fdw.py
FDW_SERVER_NAME = "syllabus_server"
FDW_USER_MAPPING = "lis"
FDW_FOREIGN_TABLE = "syllabus_items"
```

---

### 7. Definition of Done & Verification

**Test Matrix:**
| Test ID | Type | Assertion | Command |
|---------|------|-----------|---------|
| T11.1 | I | Syllabus item hierarchy (parent/child) inserts and reads correctly | `pytest tests/test_syllabus.py::test_hierarchy -v` |
| T11.2 | I | FDW query from PG-MAIN returns rows from PG-SYLLABUS | `pytest tests/test_syllabus.py::test_fdw_query -v` |
| T11.3 | I | Join between local `subjects` and foreign `syllabus_items` returns correct rows | `pytest tests/test_syllabus.py::test_fdw_join -v` |
| T11.4 | I | PG-SYLLABUS unavailable → FDW query fails cleanly with handled error, not a hang | `pytest tests/test_syllabus.py::test_fdw_failure -v` |
| T11.5 | S | FDW user mapping has read-only rights from PG-MAIN's side | `pytest tests/test_syllabus.py::test_fdw_readonly -v` |

**Verification Commands:**
```bash
# Test PG-SYLLABUS migration
uv run alembic -x dbname=lis_syllabus upgrade head && \
uv run alembic -x dbname=lis_syllabus downgrade base && \
# Test FDW from PG-MAIN
uv run pytest tests/ -m integration -v -k "syllabus or fdw" && \
uv run mypy --strict src/db/repositories/syllabus_repo.py
```

---

### 8. Failure Modes & Self-Correction

| Failure | Detection | Correction |
|---------|-----------|------------|
| FDW connection refused | T11.2 fails | Ensure PG-SYLLABUS container running; check hostname/port |
| FDW user can write | T11.5 fails | `REVOKE INSERT, UPDATE, DELETE ON syllabus_items FROM lis;` |
| FDW timeout on large joins | T11.3 slow | Add `subject_id` index on both sides; use `LIMIT` for pagination |
| Hierarchy cycle | Infinite loop in tree traversal | Application guard: track visited nodes; max depth 10 |
| FDW password in plain text | Security audit fail | Store in SOPS-encrypted secret; inject via env var |
| pgAdmin not showing FDW table | Manual check fail | Ensure `servers.json` includes both PG-MAIN and PG-SYLLABUS |
| Separate Alembic heads | Migration conflict | Use separate `alembic.ini` or `-x dbname=` parameter |
