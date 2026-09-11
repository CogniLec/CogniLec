# S12 — Row-Level Security & Auth Stub
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Implement JWT auth via fastapi-users (single-user pilot scope), enable RLS on all partitioned tables, enforce data isolation at PostgreSQL level independent of application correctness.

**Component Boundaries:**
- **Allowed:** `src/api/routes/auth.py`, `src/api/dependencies/`, `src/db/repositories/`, migrations, `tests/`
- **Off-limits:** Full IdP integration (S72), multi-user tenancy (S72), production auth hardening

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| python-jose | 3.3.x | JWT encoding/decoding |
| passlib | 1.7.x | Password hashing |
| argon2-cffi | 23.1.x | Argon2id hashing |
| fastapi | 0.141.1 | Auth endpoints |
| pytest | 8.3.x | Auth tests |

---

### 2. State Machine & Domain Schemas

**Auth Flow:**
```
POST /auth/register → hashed_password stored → 201
POST /auth/login    → JWT issued (access + refresh) → 200
GET  /auth/me       → JWT validated → user profile → 200
```

**JWT Payload:**
```json
{
  "sub": "user-uuid",
  "exp": 1726166400,
  "iat": 1726159200,
  "type": "access"
}
```

**RLS Policy (applied to all partitioned tables):**
```sql
-- Enable RLS on each table
ALTER TABLE subjects ENABLE ROW LEVEL SECURITY;
ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE utterances ENABLE ROW LEVEL SECURITY;
ALTER TABLE segments ENABLE ROW LEVEL SECURITY;
ALTER TABLE note_sections ENABLE ROW LEVEL SECURITY;
ALTER TABLE note_provenance ENABLE ROW LEVEL SECURITY;

-- Policy: users can only see their own subjects' data
CREATE POLICY user_isolation ON subjects
    USING (user_id = current_setting('app.user_id')::UUID);

CREATE POLICY user_isolation_on_sessions ON sessions
    USING (subject_id IN (
        SELECT id FROM subjects WHERE user_id = current_setting('app.user_id')::UUID
    ));

CREATE POLICY user_isolation_on_utterances ON utterances
    USING (subject_id IN (
        SELECT id FROM subjects WHERE user_id = current_setting('app.user_id')::UUID
    ));

-- ... similar for segments, note_sections, note_provenance
```

**Session Variable Middleware:**
```python
# Per-request: SET LOCAL app.user_id = $1
# In repository layer, before any query:
await session.execute(text("SET LOCAL app.user_id = :user_id"), {"user_id": str(user_id)})
```

**SQLAlchemy Models (auth):**
```python
# src/db/models/user.py (from S07)
class User(Base):
    __tablename__ = "users"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    email: Mapped[str] = mapped_column(Citext, unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
```

**Pydantic Schemas:**
```python
# src/api/schemas/auth.py
class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)

class UserResponse(BaseModel):
    id: UUID
    email: str
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

class TokenPayload(BaseModel):
    sub: str
    exp: int
    iat: int
    type: Literal["access", "refresh"]
```

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Create auth endpoints (register, login, me) | `curl -X POST /auth/register` returns 201 |
| 2 | Implement Argon2id password hashing | Password stored as hash, never plaintext |
| 3 | Implement JWT token generation + validation | T12.3 passes |
| 4 | Enable RLS on all partitioned tables | `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` |
| 5 | Create RLS policies for user isolation | T12.1-T12.2 pass |
| 6 | Implement `SET LOCAL app.user_id` in repository layer | T12.5 passes |
| 7 | Add auth dependency injection for FastAPI | Protected endpoints require JWT |
| 8 | Write integration tests with direct SQL bypass | T12.1 passes |

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| Expired JWT | Return 401; client must refresh |
| Missing `app.user_id` session variable | RLS returns zero rows (fail-closed, T12.5) |
| Direct SQL bypass of API | RLS still enforced at DB level (T12.1) |
| Password in plaintext anywhere | Never; Argon2id hash only (T12.4) |
| User A tries to access User B's data | RLS blocks at DB level |
| RLS policy syntax error | Migration fails; test with `pgBadger` or manual SQL |

---

### 4. Code Style & Architecture Constraints

- **Pattern:** FastAPI dependency injection for auth
- **Password hashing:** Argon2id (via `argon2-cffi`), never bcrypt for new systems
- **JWT:** Short-lived access (30min), longer refresh (7d)
- **RLS enforcement:** At PostgreSQL level, not application level
- **Session variable:** Set per-request via `SET LOCAL` (transaction-scoped)
- **Fail-closed:** Missing user_id → zero rows, never all rows
- **No plaintext passwords** anywhere: logs, error messages, API responses

---

### 5. API & Interface Contracts

**Auth Endpoints:**
```
POST   /api/v1/auth/register  → 201 UserResponse
POST   /api/v1/auth/login     → 200 TokenResponse
GET    /api/v1/auth/me         → 200 UserResponse
POST   /api/v1/auth/refresh    → 200 TokenResponse
```

**Request/Response Payloads:**
```json
// POST /api/v1/auth/register
// Request:
{ "email": "user@example.com", "password": "securepass123" }
// Response 201:
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "email": "user@example.com",
  "is_active": true,
  "created_at": "2026-09-12T10:30:00Z"
}

// POST /api/v1/auth/login
// Request:
{ "email": "user@example.com", "password": "securepass123" }
// Response 200:
{
  "access_token": "<jwt-access-token>",
  "refresh_token": "<jwt-refresh-token>",
  "token_type": "bearer"
}

// GET /api/v1/auth/me
// Headers: Authorization: Bearer <access_token>
// Response 200: (UserResponse)
```

**RLS Policy SQL:**
```sql
-- Applied to each table via migration
ALTER TABLE subjects ENABLE ROW LEVEL SECURITY;
ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE utterances ENABLE ROW LEVEL SECURITY;
ALTER TABLE segments ENABLE ROW LEVEL SECURITY;
ALTER TABLE note_sections ENABLE ROW LEVEL SECURITY;
ALTER TABLE note_provenance ENABLE ROW LEVEL SECURITY;

-- Subject-level policy
CREATE POLICY user_isolation_subjects ON subjects
    USING (user_id = current_setting('app.user_id')::UUID);

-- Cascading policy for child tables
CREATE POLICY user_isolation_sessions ON sessions
    USING (subject_id IN (
        SELECT id FROM subjects WHERE user_id = current_setting('app.user_id')::UUID
    ));
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Default |
|----------|------|-------------|---------|
| `SECRET_KEY` | string | JWT signing key (32+ hex chars) | `changeme` |
| `ALGORITHM` | string | JWT algorithm | `HS256` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | int | Access token TTL | `30` |
| `REFRESH_TOKEN_EXPIRE_DAYS` | int | Refresh token TTL | `7` |

**Additional Dependencies (pyproject.toml):**
- `python-jose[cryptography]>=3.3,<4.0`
- `passlib[bcrypt]>=1.7,<2.0`
- `argon2-cffi>=23.1,<25.0`

---

### 7. Definition of Done & Verification

**Test Matrix:**
| Test ID | Type | Assertion | Command |
|---------|------|-----------|---------|
| T12.1 | I | User A cannot read User B's subjects **even with a direct SQL query** bypassing the API | `pytest tests/test_rls.py::test_rls_cross_user_sql -v` |
| T12.2 | I | RLS blocks cross-user utterance reads | `pytest tests/test_rls.py::test_rls_cross_user_utterances -v` |
| T12.3 | U | JWT expiry honoured; expired token rejected | `pytest tests/test_auth.py::test_jwt_expiry -v` |
| T12.4 | S | Password stored as Argon2id, never plaintext or reversible | `pytest tests/test_auth.py::test_password_hashing -v` |
| T12.5 | I | Missing `app.user_id` session variable → zero rows, never all rows (fail-closed) | `pytest tests/test_rls.py::test_rls_fail_closed -v` |

**Verification Commands:**
```bash
# Full auth + RLS verification
uv run pytest tests/ -m integration -v -k "auth or rls" && \
uv run mypy --strict src/api/routes/auth.py src/api/dependencies/ && \
uv run ruff check src/api/routes/auth.py
```

**Manual Verification:**
```sql
-- Connect as user A, try to read user B's data
SET LOCAL app.user_id = 'user-a-uuid';
SELECT * FROM subjects;  -- Only user A's subjects

-- Without setting app.user_id
RESET app.user_id;
SELECT * FROM subjects;  -- Zero rows (fail-closed)
```

---

### 8. Failure Modes & Self-Correction

| Failure | Detection | Correction |
|---------|-----------|------------|
| RLS not enforced on direct SQL | T12.1 fails | Ensure `ENABLE ROW LEVEL SECURITY` ran on ALL tables |
| Fail-open instead of fail-closed | T12.5 fails | Policy must use `USING (user_id = current_setting('app.user_id')::UUID)` without fallback |
| JWT validation bypassed | T12.3 fails | Ensure all protected endpoints use `Depends(get_current_user)` |
| Password stored in plaintext | T12.4 fails | Check `users.hashed_password` column; Argon2id hash must be present |
| `SET LOCAL` not transaction-scoped | RLS leak | Use `SET LOCAL` not `SET`; it auto-resets at transaction end |
| Secret key hardcoded | Security audit fail | Load from env; never commit `.env` |
| RLS policy on non-partitioned table | Table missing RLS | Add RLS to `note_assets` too (even though not partitioned) |
