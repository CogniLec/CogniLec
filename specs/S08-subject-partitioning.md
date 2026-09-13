# S08 — Subject Partitioning Machinery
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Implement per-subject table provisioning as a single transaction: insert subject → `CREATE TABLE ... PARTITION OF` for each partitioned table → create per-partition HNSW indexes. Subject isolation enforced by PostgreSQL query planner, not application code.

**Component Boundaries:**
- **Allowed:** `src/db/partitions/`, `src/db/models/`, migrations, `src/db/repositories/`, tests
- **Off-limits:** Utterance/segment content columns (S09), notes (S10), auth/RLS (S12)

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| PostgreSQL | 17 | LIST partitioning |
| pg_partman | (bundled) | Partition lifecycle |
| pgvector | 0.5.0 | HNSW indexes per partition |
| SQLAlchemy | 2.0.52 | DDL execution |
| testcontainers | 4.6.x | Integration tests |

---

### 2. State Machine & Domain Schemas

**Partitioned Tables (declared in S07/S09/S10, partitioned here):**
- `utterances` — S09 defines columns
- `segments` — S09 defines columns
- `note_sections` — S10 defines columns
- `note_provenance` — S10 defines columns

**Partition Strategy (ADR-005):**
```
PARTITION BY LIST (subject_id)
```
Each subject gets its own partition. Primary key includes `subject_id` as leading column: `PRIMARY KEY (subject_id, id)`.

**Provisioning Transaction:**
```sql
BEGIN;
  INSERT INTO subjects (id, user_id, name) VALUES ($1, $2, $3) RETURNING id;

  CREATE TABLE utterances_{subject_id} PARTITION OF utterances
    FOR VALUES IN ($1);
  CREATE TABLE segments_{subject_id} PARTITION OF segments
    FOR VALUES IN ($1);
  CREATE TABLE note_sections_{subject_id} PARTITION OF note_sections
    FOR VALUES IN ($1);
  CREATE TABLE note_provenance_{subject_id} PARTITION OF note_provenance
    FOR VALUES IN ($1);

  CREATE INDEX idx_utt_{subject_id}_embedding ON utterances_{subject_id}
    USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
  CREATE INDEX idx_seg_{subject_id}_embedding ON segments_{subject_id}
    USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
COMMIT;
```

**Deprovisioning:**
```sql
BEGIN;
  DROP TABLE IF EXISTS utterances_{subject_id};
  DROP TABLE IF EXISTS segments_{subject_id};
  DROP TABLE IF EXISTS note_sections_{subject_id};
  DROP TABLE IF EXISTS note_provenance_{subject_id};
  DELETE FROM subjects WHERE id = $1;
COMMIT;
```

**Parent Table DDL Template (created in migration):**
```sql
CREATE TABLE utterances (
    subject_id UUID NOT NULL,
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES sessions(id),
    seq INTEGER NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    text TEXT NOT NULL,
    asr_confidence FLOAT,
    speaker_tag VARCHAR(10),
    embedding vector(1024),
    embed_model_ver VARCHAR(50) NOT NULL,
    topic_id UUID,
    is_relevant BOOLEAN,
    filter_reason VARCHAR(100),
    outlier_score FLOAT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (subject_id, id),
    UNIQUE (subject_id, session_id, seq)
) PARTITION BY LIST (subject_id);

CREATE TABLE segments (
    subject_id UUID NOT NULL,
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES sessions(id),
    start_utt UUID NOT NULL,
    end_utt UUID NOT NULL,
    topic_id UUID,
    boundary_score FLOAT,
    confidence FLOAT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (subject_id, id)
) PARTITION BY LIST (subject_id);

CREATE TABLE note_sections (
    subject_id UUID NOT NULL,
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    topic_id UUID,
    session_id UUID,
    heading TEXT NOT NULL,
    body_md TEXT NOT NULL,
    depth INTEGER NOT NULL DEFAULT 0,
    ordinal INTEGER NOT NULL,
    embedding vector(1024),
    model_version VARCHAR(50),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (subject_id, id)
) PARTITION BY LIST (subject_id);

CREATE TABLE note_provenance (
    subject_id UUID NOT NULL,
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    note_section_id UUID NOT NULL,
    utterance_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (subject_id, id)
) PARTITION BY LIST (subject_id);
```

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Create `src/db/partitions/__init__.py` | Import succeeds |
| 2 | Implement `PartitionProvisioner` class | Unit tests pass |
| 3 | Create provisioning function (single transaction) | T08.1 passes |
| 4 | Create deprovisioning function | T08.4 passes |
| 5 | Add `EXPLAIN`-based partition pruning assertion | T08.2 passes |
| 6 | Add query-without-subject-id guard in repository | T08.3 passes |
| 7 | Write migration creating parent tables with `PARTITION BY LIST` | Migration applies cleanly |
| 8 | Write concurrent provisioning test | T08.6 passes |
| 9 | Add performance test for provisioning speed | T08.5 passes |

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| Provisioning a subject that already exists | Reject with `SubjectAlreadyExistsError` |
| Deprovisioning a subject with active sessions | Allow (CASCADE handles it) |
| Concurrent provisioning deadlocks | Use `SAVEPOINT` + retry on deadlock (max 3 attempts) |
| Partition name collision | Use UUID in partition name: `utterances_{subject_id_hex[:8]}` |
| HNSW index creation fails (OOM) | Log warning, proceed without index; index can be added later |
| Parent table doesn't exist yet | Provisioning function checks `pg_class` for parent table existence |

---

### 4. Code Style & Architecture Constraints

- **Pattern:** Repository + Service (PartitionProvisioner)
- **Naming:** `utterances_{short_uuid}` for partition table names (max 63 chars PG limit)
- **Transaction:** All provisioning in ONE transaction — no partial provision
- **Index params:** HNSW `m=16, ef_construction=64` (tunable later)
- **Error handling:** Custom exceptions in `src/db/exceptions.py`
- **Logging:** `structlog` on every provisioning/deprovisioning event
- **No raw SQL in application code** — use `text()` for DDL only (DDL not ORM-mappable)

---

### 5. API & Interface Contracts

**Provisioning Service Interface:**
```python
# src/db/partitions/provisioner.py
class PartitionProvisioner:
    async def provision_subject(
        self, session: AsyncSession, user_id: UUID, name: str, description: str | None = None
    ) -> Subject:
        """Create subject + all partitions + HNSW indexes in one transaction."""

    async def deprovision_subject(self, session: AsyncSession, subject_id: UUID) -> None:
        """Drop all partitions + subject in one transaction."""

    async def subject_partitions_exist(self, session: AsyncSession, subject_id: UUID) -> bool:
        """Check if partitions exist for a subject."""
```

**Repository Guard:**
```python
# src/db/repositories/base.py
class BaseRepository:
    def _require_subject_id(self, subject_id: UUID | None) -> UUID:
        """Reject queries without subject_id to enforce partition pruning."""
        if subject_id is None:
            raise ValueError("subject_id is required for partitioned queries")
        return subject_id
```

---

### 6. Dependency & Environment Configuration

**Required Services:**
- PG-MAIN with `pgvector` and `pg_partman` extensions (S03)
- Test PG via testcontainers (S13)

**Environment Variables:**
- `DATABASE_URL` — PG-MAIN connection string

**Partition Config:**
```python
# src/db/partitions/config.py
PARTITIONED_TABLES = ["utterances", "segments", "note_sections", "note_provenance"]
HNSW_M = 16
HNSW_EF_CONSTRUCTION = 64
HNSW_EF_SEARCH = 32
PROVISION_TIMEOUT_SECONDS = 2
```

---

### 7. Definition of Done & Verification

**Test Matrix:**
| Test ID | Type | Assertion | Command |
|---------|------|-----------|---------|
| T08.1 | I | Creating a subject produces all expected partitions and indexes | `pytest tests/test_partitions.py::test_provision_creates_partitions -v` |
| T08.2 | I | `EXPLAIN` on subject_id-filtered query shows partition pruning | `pytest tests/test_partitions.py::test_partition_pruning -v` |
| T08.3 | I | Query without subject_id filter rejected by repository layer | `pytest tests/test_partitions.py::test_missing_subject_id_rejected -v` |
| T08.4 | I | Subject deletion drops its partitions; other subjects' data intact | `pytest tests/test_partitions.py::test_deprovision_cleans_up -v` |
| T08.5 | P | Provisioning a subject completes in < 2s | `pytest tests/test_partitions.py::test_provision_performance -v --timeout=5` |
| T08.6 | I | 50 subjects provisioned concurrently without deadlock | `pytest tests/test_partitions.py::test_concurrent_provision -v` |

**Verification Commands:**
```bash
uv run pytest tests/ -m integration -v -k "partition" && \
uv run mypy --strict src/db/partitions/ && \
uv run ruff check src/db/partitions/
```

---

### 8. Failure Modes & Self-Correction

| Failure | Detection | Correction |
|---------|-----------|------------|
| Partition name exceeds 63 chars | PG error on CREATE TABLE | Use `subject_id_hex[:8]` prefix (max 8 + table name < 63) |
| Deadlock on concurrent provisioning | T08.6 fails | Add SAVEPOINT + retry loop with exponential backoff |
| HNSW index creation OOM on 4GB VRAM | Index build fails | Skip HNSW at provision time; add later via maintenance job |
| EXPLAIN doesn't show pruning | T08.2 fails | Ensure query has `WHERE subject_id = $1` as first condition |
| Deprovision leaves orphan partitions | T08.4 fails | Use `DROP TABLE IF EXISTS` for each partition in transaction |
| Parent table not found | Provisioning fails | Check migration ran; parent tables must exist before provisioning |
