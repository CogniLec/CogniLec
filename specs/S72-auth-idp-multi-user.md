# S72 — Auth, IdP & Multi-User
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Replace the S12 auth stub with Authentik (OIDC) for production authentication, verify multi-user tenancy against existing RLS policies, and implement full data export and account deletion with cascade across all three databases and the object store (NFR-S6, AC-20).

**Component Boundaries:**
- **Allowed:** `docker/compose/auth/`, `src/auth/`, `src/api/routes/auth.py`, `src/api/routes/users.py`, `config/authentik/`, `tests/`
- **Off-limits:** Database schemas (S07), RLS policies (S12), core agent logic, model serving

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| Authentik | 2024.x | OIDC Identity Provider |
| FastAPI | 0.141.1 | API framework |
| httpx | 0.27.x | OIDC token exchange |
| python-jose | 3.3.x | JWT validation |
| SQLAlchemy | 2.0.52 | ORM |
| Pydantic | 2.13.5 | Validation |

---

### 2. State Machine & Domain Schemas

**User Lifecycle:**
```
registered -> active -> (deactivating -> deleted)
                   -> (suspended -> active | deleted)
```

**OIDC Token Flow:**
```
Browser -> Authentik (login) -> Authentik issues OIDC tokens
Browser -> API (access_token) -> API validates via Authentik JWKS
```

**SQLAlchemy Models (updated from S07):**
```python
class User(Base):
    __tablename__ = "users"
    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    email: Mapped[str] = mapped_column(Citext, unique=True, nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    auth_provider: Mapped[str] = mapped_column(String(50), nullable=False, default="local")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DeletionAudit(Base):
    __tablename__ = "deletion_audit"
    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    user_email: Mapped[str] = mapped_column(String(255), nullable=False)
    initiated_by: Mapped[str] = mapped_column(String(255), nullable=False)
    db1_records_deleted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    db2_records_deleted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    db3_records_deleted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    object_store_files_deleted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
```

**Pydantic Schemas:**
```python
class OIDCLoginRequest(BaseModel):
    code: str
    redirect_uri: str
    state: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: "UserResponse"


class DataExportResponse(BaseModel):
    export_id: UUID
    status: str  # pending, processing, ready
    download_url: str | None = None
    expires_at: datetime | None = None


class AccountDeletionRequest(BaseModel):
    confirm_email: str = Field(..., description="User must type email to confirm")


class DeletionAuditResponse(BaseModel):
    id: UUID
    user_id: UUID
    user_email: str
    initiated_by: str
    db1_records_deleted: int
    db2_records_deleted: int
    db3_records_deleted: int
    object_store_files_deleted: int
    completed_at: datetime
```

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Deploy Authentik via docker-compose | Authentik UI accessible |
| 2 | Configure Authentik OIDC provider for LIS | OIDC discovery endpoint valid |
| 3 | Create Authentik application and OAuth2 client | Client ID/secret configured |
| 4 | Update API auth middleware for OIDC token validation | `GET /api/v1/auth/me` works with valid token |
| 5 | Update RLS policies for Authentik user IDs | RLS isolation verified (re-run S12 T12.1/T12.2) |
| 6 | Implement data export endpoint | Export produces complete archive |
| 7 | Implement account deletion cascade | Deletion removes all data across all stores |
| 8 | Create deletion audit table migration | Audit record created on deletion |
| 9 | Verify deletion by direct DB and bucket inspection | No data remains |
| 10 | Test 20 concurrent users with isolation | No cross-user data leakage |
| 11 | Run all T72.x tests | All pass |

**Atomic Sub-tasks:**
1. Authentik deployment and OIDC configuration
2. API auth middleware update for OIDC token validation
3. RLS policy update for Authentik user IDs
4. Data export endpoint implementation
5. Account deletion cascade implementation
6. Deletion audit logging
7. Multi-user isolation testing

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| Authentik unreachable | Return 503; cache last-known-valid tokens briefly |
| Token expired | Return 401; client must refresh |
| User deleted while active session exists | Invalidate all sessions; return 401 on next request |
| Data export fails mid-generation | Clean up partial export; retry from checkpoint |
| Deletion cascade fails on one store | Log failure; mark as partial; alert operator |
| OIDC callback URL mismatch | Reject with 400; log security event |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- OIDC Authorization Code Flow with PKCE
- Repository Pattern for user data access
- Cascade delete pattern across multiple stores
- Audit logging for compliance

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase
- Files: snake_case.py
- Auth routes: `src/api/routes/auth.py`
- User routes: `src/api/routes/users.py`
- Auth middleware: `src/auth/middleware.py`

**Code Splitting Metrics:**
- Max function length: 40 lines
- Max file length: 300 lines
- Auth middleware: separate from route handlers
- Deletion cascade: separate from route handlers

**Type Safety:**
- All function signatures must have type hints
- JWT claims validated with strict Pydantic models
- OIDC tokens validated against Authentik JWKS

---

### 5. API & Interface Contracts

**FastAPI Endpoints:**
```
POST   /api/v1/auth/oidc/login       -> 200 TokenResponse
POST   /api/v1/auth/oidc/refresh     -> 200 TokenResponse
POST   /api/v1/auth/oidc/callback    -> 302 redirect with tokens
GET    /api/v1/auth/me               -> 200 UserResponse
POST   /api/v1/auth/logout           -> 204

GET    /api/v1/users/me              -> 200 UserResponse
POST   /api/v1/users/me/export       -> 202 DataExportResponse
GET    /api/v1/users/me/export/{id}  -> 200 DataExportResponse
DELETE /api/v1/users/me              -> 202 DeletionAuditResponse

GET    /api/v1/admin/users           -> 200 list[UserResponse]
DELETE /api/v1/admin/users/{id}      -> 202 DeletionAuditResponse
```

**Deletion Cascade SQL (per database):**
```sql
-- DB-1 (PG-MAIN)
DELETE FROM agent_runs WHERE session_id IN (
  SELECT id FROM sessions WHERE subject_id IN (
    SELECT id FROM subjects WHERE user_id = $1));
DELETE FROM utterances WHERE segment_id IN (
  SELECT id FROM segments WHERE session_id IN (
    SELECT id FROM sessions WHERE subject_id IN (
      SELECT id FROM subjects WHERE user_id = $1)));
DELETE FROM segments WHERE session_id IN (
  SELECT id FROM sessions WHERE subject_id IN (
    SELECT id FROM subjects WHERE user_id = $1));
DELETE FROM sessions WHERE subject_id IN (
  SELECT id FROM subjects WHERE user_id = $1);
DELETE FROM subjects WHERE user_id = $1;

-- DB-2 (PG-SYLLABUS)
DELETE FROM note_sections WHERE session_id IN (
  SELECT id FROM sessions WHERE subject_id IN (
    SELECT id FROM subjects WHERE user_id = $1));
DELETE FROM notes WHERE session_id IN (
  SELECT id FROM sessions WHERE subject_id IN (
    SELECT id FROM subjects WHERE user_id = $1));

-- DB-3 (FDW)
DELETE FROM syllabus_items WHERE subject_id IN (
  SELECT id FROM subjects WHERE user_id = $1);

-- Object Store: DELETE /lis-data/{user_id}/*
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Example |
|----------|------|-------------|---------|
| `AUTHENTIK_URL` | string | Authentik server URL | `http://authentik:9000` |
| `AUTHENTIK_CLIENT_ID` | string | OAuth2 client ID | `lis-backend` |
| `AUTHENTIK_CLIENT_SECRET` | string | OAuth2 client secret | `changeme-...` |
| `AUTHENTIK_ISSUER` | string | OIDC issuer URL | `http://authentik:9000/application/o/lis/` |
| `OIDC_REDIRECT_URI` | string | OAuth2 redirect URI | `https://app.example.com/auth/callback` |
| `DATA_EXPORT_BUCKET` | string | Bucket for export archives | `lis-exports` |
| `DATA_EXPORT_TTL_HOURS` | int | Export file retention | `24` |

**Third-Party Integration Contracts:**
- Authentik: OIDC provider with JWKS, token introspection, user management
- MinIO: Object store for user file deletion and export storage

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Given | When | Then |
|---------|------|-------|------|------|
| T72.1 | E | Authentik configured with OIDC provider | User completes OIDC login flow | Login succeeds; tokens issued; logout invalidates tokens; refresh produces new tokens |
| T72.2 | I | Authentik providing user IDs; RLS policies active | Create users A and B; user A queries data | User A sees only their data; user B sees only theirs (re-run S12 T12.1/T12.2) |
| T72.3 | I | User with data in DB-1, DB-2, DB-3, and object store | Account deletion requested with email confirmation | All data removed across all three databases and object store (AC-20) |
| T72.4 | I | User with subjects, sessions, notes, and syllabus items | Data export requested | Complete, readable archive produced containing only the user's own data |
| T72.5 | S | Account deletion completed | Inspect DB-1, DB-2, DB-3, and object store directly | No traces of deleted user's data remain (verified by direct query, not API response) |
| T72.6 | I | 20 concurrent authenticated users | Each user creates and queries their own data | All users isolated correctly; no cross-user data leakage under concurrent load |

**Verification Commands:**
```bash
# Verify Authentik OIDC
curl -s http://localhost:9000/application/o/lis/.well-known/openid-configuration | jq .issuer

# Verify API auth
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/auth/me | jq .

# Verify RLS isolation
uv run pytest tests/ -m integration -v -k "rls_isolation"

# Verify deletion cascade
uv run pytest tests/ -m integration -v -k "account_deletion"

# Full verification
uv run pytest tests/ -m integration -v -k "S72 or auth or oidc or deletion"
```

**Exit Criteria:**
- [ ] OIDC login, logout and token refresh work (T72.1)
- [ ] RLS holds under new auth (T72.2)
- [ ] Account deletion removes all data across all stores (T72.3)
- [ ] Data export produces complete, readable archive (T72.4)
- [ ] Deletion verified by direct DB and bucket inspection (T72.5)
- [ ] 20 concurrent users isolated correctly (T72.6)

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- Authentik JWKS rotation can cause brief token validation failures; cache JWKS with short TTL
- OIDC callback URL must match exactly (including trailing slash); configure in both Authentik and app
- Deletion cascade across multiple databases is not atomic; use saga pattern with compensating actions
- RLS policies must reference Authentik `external_id`, not internal user ID
- Export archives can be large; generate asynchronously and stream download

**Fallback Instructions:**
- If Authentik is down, fall back to local password auth (maintain dual-mode)
- If deletion cascade fails on one store, mark as partial and retry
- If export generation fails, clean up partial files and retry

**Rollback Procedure:**
- Auth: revert auth middleware to S12 stub; re-enable local password auth
- Deletion: no rollback (deletions are permanent); ensure backups exist
- Config: revert `config/authentik/` and docker-compose changes

---

### 9. Observability (if applicable)

**Metrics Added:**
- `lis_auth_login_total{provider, status}`: Counter of login attempts
- `lis_auth_token_refresh_total{status}`: Counter of token refreshes
- `lis_auth_deletion_total{initiated_by, status}`: Counter of account deletions
- `lis_auth_export_total{status}`: Counter of data export requests
- `lis_auth_active_sessions`: Gauge of active authenticated sessions

**Tracing/Logging:**
- Span: `auth.oidc_login` for OIDC login flow
- Span: `auth.token_validate` for JWT validation
- Span: `auth.deletion_cascade` for account deletion
- Log event: `user_login` with provider, user_id
- Log event: `user_logout` with user_id
- Log event: `account_deletion_initiated` with user_id, initiated_by
- Log event: `account_deletion_completed` with user_id, counts per store

**Alerts:**
- Alert if login failure rate > 20% (possible attack)
- Alert if deletion cascade fails
- Alert if Authentik health check fails

---

### 10. Exit Checklist

- [ ] All tests pass (T72.1, T72.2, T72.3, T72.4, T72.5, T72.6)
- [ ] Authentik OIDC integration working
- [ ] RLS isolation verified under new auth
- [ ] Account deletion cascades across all stores
- [ ] Data export produces complete archive
- [ ] Deletion verified by direct inspection
- [ ] 20 concurrent users isolated correctly
- [ ] Observability metrics and alerts configured
