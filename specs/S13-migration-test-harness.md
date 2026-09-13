# S13 — Migration & Test Harness
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Build testcontainers-python fixture spinning real PG17+pgvector per test session, pgTAP suite for constraints/RLS/partitioning, Faker-based synthetic lecture transcript generator, and CI integration job.

**Component Boundaries:**
- **Allowed:** `tests/`, `src/eval/`, `src/db/`, CI workflow updates
- **Off-limits:** Application logic in `src/` (tested by other stages)

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| testcontainers | 4.6.x | PG containers per test |
| pgTAP | via `pg_prove` | DB constraint/RLS testing |
| Faker | 30.1.x | Synthetic data generation |
| factory-boy | 3.3.x | Test factories |
| hypothesis | 6.101.x | Property-based testing |
| pytest-xdist | 3.5.x | Parallel test execution |
| pytest-timeout | 2.3.x | Test timeout enforcement |

---

### 2. State Machine & Domain Schemas

**Testcontainers Fixture Pattern:**
```python
# tests/conftest.py
import pytest
from testcontainers.postgres import PostgresContainer


@pytest.fixture(scope="session")
def pg_container():
    """Spin up PG17+pgvector for the entire test session."""
    with PostgresContainer(
        "pgvector/pgvector:pg17",
        port=5432,
        user="lis",
        password="test",
        dbname="lis_test",
    ) as pg:
        # Wait for extensions
        pg.exec("CREATE EXTENSION IF NOT EXISTS vector;")
        pg.exec('CREATE EXTENSION IF NOT EXISTS "uuid-ossp";')
        pg.exec("CREATE EXTENSION IF NOT EXISTS citext;")
        yield pg


@pytest.fixture(scope="function")
def db_session(pg_container):
    """Provide a clean DB session per test, rollback after."""
    engine = create_async_engine(pg_container.get_connection_url())
    async with engine.begin() as conn:
        # Run all migrations
        await conn.run_async(do_run_migrations)
        # Set up RLS
        await conn.execute(text("ALTER TABLE subjects ENABLE ROW LEVEL SECURITY;"))
        # ...
    session = AsyncSession(engine)
    yield session
    # Rollback
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    await engine.dispose()
```

**Synthetic Transcript Generator:**
```python
# src/eval/synthetic.py
class SyntheticTranscriptGenerator:
    """Generate realistic lecture transcripts for testing."""

    def generate(
        self,
        num_topics: int = 3,
        utterances_per_topic: int = 50,
        include_off_topic: bool = True,
        off_topic_ratio: float = 0.1,
        include_discussion: bool = False,
    ) -> SyntheticTranscript:
        """
        Returns:
            SyntheticTranscript with:
            - utterances: list[dict] with text, start_ms, end_ms, speaker
            - topic_boundaries: list[int] (utterance indices where topic changes)
            - topic_labels: list[str]
            - expected_segments: list[dict] with start_idx, end_idx, topic
        """


# SyntheticTranscript model
class SyntheticTranscript(BaseModel):
    utterances: list[SyntheticUtterance]
    topic_boundaries: list[int]
    topic_labels: list[str]
    expected_segments: list[ExpectedSegment]


class SyntheticUtterance(BaseModel):
    text: str
    start_ms: int
    end_ms: int
    speaker: str  # "lecturer" or "student"
    is_off_topic: bool = False
    topic_idx: int
```

**pgTAP Test Patterns:**
```sql
-- tests/pgtap/test_constraints.sql
BEGIN;
SELECT plan(5);

-- Test: session status check constraint
SELECT lives_ok(
    $$INSERT INTO sessions (subject_id, status) VALUES ('00000000-0000-0000-0000-000000000001', 'created')$$,
    'Session with valid status inserts'
);

SELECT throws_ok(
    $$INSERT INTO sessions (subject_id, status) VALUES ('00000000-0000-0000-0000-000000000001', 'invalid_status')$$,
    23514,  -- check_violation
    NULL,
    'Session with invalid status is rejected'
);

-- Test: unique subject name per user
SELECT lives_ok(
    $$INSERT INTO subjects (user_id, name) VALUES ('00000000-0000-0000-0000-000000000001', 'ML')$$,
    'Subject inserts for user'
);

SELECT throws_ok(
    $$INSERT INTO subjects (user_id, name) VALUES ('00000000-0000-0000-0000-000000000001', 'ML')$$,
    23505,  -- unique_violation
    NULL,
    'Duplicate subject name for same user rejected'
);

SELECT * FROM finish();
ROLLBACK;
```

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Create `tests/conftest.py` with testcontainers fixture | `pytest --co` collects tests |
| 2 | Create `tests/pgtap/` directory with pgTAP SQL tests | `pg_prove` runs all SQL tests |
| 3 | Implement `SyntheticTranscriptGenerator` | T13.2 passes |
| 4 | Create test factories for User, Subject, Session, Utterance | Factory imports succeed |
| 5 | Write pgTAP suite for constraints + RLS + partitioning | T13.3 passes |
| 6 | Write migration round-trip test | T13.4 passes |
| 7 | Update CI to run integration tests on `main` | CI job green |
| 8 | Add `pytest.ini_options` marker for `integration` | `pytest -m integration` works |

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| testcontainers PG fails to start | CI service timeout; increase wait; check Docker |
| pgTAP not installed in test PG | Install via `CREATE EXTENSION IF NOT EXISTS pgTAP;` |
| Migration fails on test DB | Test catches it; must be fixed before other tests run |
| Synthetic data unrealistic | Validate against S04 corpus statistics |
| Test isolation not clean | DROP SCHEMA + CREATE SCHEMA between tests |
| Parallel test interference | Use unique DB names or schema per test |

---

### 4. Code Style & Architecture Constraints

- **Pattern:** pytest fixtures with `scope="session"` for containers, `scope="function"` for sessions
- **Test naming:** `test_<what>_<condition>` (snake_case)
- **Factory pattern:** factory-boy `Factory` classes for test data
- **Hypothesis:** Property tests for invariant checking (e.g., segments are contiguous)
- **pgTAP:** SQL-based tests run via `pg_prove` or embedded in pytest
- **No external test dependencies** beyond what's in `pyproject.toml[project.optional-dependencies.dev]`
- **Test database:** Separate from dev/prod; created/destroyed per test run

---

### 5. API & Interface Contracts

**Test Fixtures (conftest.py):**
```python
@pytest.fixture
async def db_session(pg_container) -> AsyncGenerator[AsyncSession, None]:
    """Clean DB session per test."""


@pytest.fixture
def user_factory(db_session):
    """Factory for creating test users."""


@pytest.fixture
def subject_factory(db_session, user_factory):
    """Factory for creating test subjects."""


@pytest.fixture
def session_factory(db_session, subject_factory):
    """Factory for creating test sessions."""


@pytest.fixture
def synthetic_generator():
    """Synthetic transcript generator instance."""
```

**CI Integration Job:**
```yaml
# .github/workflows/ci.yml (addition)
integration-tests:
  runs-on: ubuntu-latest
  services:
    postgres:
      image: pgvector/pgvector:pg17
      env:
        POSTGRES_USER: lis
        POSTGRES_PASSWORD: test
        POSTGRES_DB: lis_test
      ports: ["5432:5432"]
      options: >-
        --health-cmd="pg_isready -U lis"
        --health-interval=10s
        --health-timeout=5s
        --health-retries=5
    valkey:
      image: valkey/valkey:8-alpine
      ports: ["6379:6379"]
  steps:
    - uses: actions/checkout@v4
    - uses: astral-sh/setup-uv@v4
    - run: uv sync --dev
    - run: uv run pytest tests/ -m integration -v --timeout=120
```

---

### 6. Dependency & Environment Configuration

**Required Services:**
- Docker (for testcontainers)
- PG17+pgvector image (testcontainers pulls automatically)

**Environment Variables (test):**
| Variable | Value | Purpose |
|----------|-------|---------|
| `DATABASE_URL` | `postgresql+asyncpg://lis:test@localhost:5432/lis_test` | Test DB |
| `TESTING` | `true` | Disable rate limiting, etc. |

**pgTAP Installation:**
```sql
-- In test setup
CREATE EXTENSION IF NOT EXISTS pgtap;
SELECT * FROM pgtap_version();
```

---

### 7. Definition of Done & Verification

**Test Matrix:**
| Test ID | Type | Assertion | Command |
|---------|------|-----------|---------|
| T13.1 | I | testcontainers fixture provides a working pgvector database | `pytest tests/test_harness.py::test_pgvector_available -v` |
| T13.2 | U | Synthetic generator produces a transcript with N declared topics and verifiable boundary positions | `pytest tests/test_harness.py::test_synthetic_generator -v` |
| T13.3 | I | Full pgTAP suite green | `pg_prove tests/pgtap/*.sql` or `pytest tests/test_pgtrap.py -v` |
| T13.4 | U | `downgrade base` → `upgrade head` round-trip on a populated database preserves nothing (clean) and errors nowhere | `pytest tests/test_harness.py::test_migration_roundtrip -v` |

**Verification Commands:**
```bash
# Full test harness verification
uv run pytest tests/ -m integration -v --timeout=120 && \
uv run pytest tests/test_harness.py -v && \
uv run mypy --strict tests/conftest.py src/eval/synthetic.py
```

---

### 8. Failure Modes & Self-Correction

| Failure | Detection | Correction |
|---------|-----------|------------|
| testcontainers can't pull Docker image | CI timeout | Use `docker pull pgvector/pgvector:pg17` as pre-step |
| pgTAP extension not available | SQL test fails | Add `CREATE EXTENSION IF NOT EXISTS pgtap;` in setup |
| Migration round-trip fails | T13.4 fails | Check `downgrade()` has proper DROP statements |
| Synthetic data too uniform | T13.2 fails | Add variance: random pauses, topic depth, off-topic ratio |
| Test isolation violated | Test passes then fails on re-run | Ensure DROP SCHEMA + CREATE SCHEMA between tests |
| Parallel test DB conflict | Test fails intermittently | Use unique DB name per xdist worker |
| testcontainers port conflict | CI fails on re-run | Use `ports=[5432]` with random port assignment |
| pg_prove not installed | SQL tests skipped | Install via `apt-get install postgresql-17-pgtap` in CI |
