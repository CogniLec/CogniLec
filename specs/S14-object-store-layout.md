# S14 — Object Store Layout & Lifecycle Policies
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Provision MinIO buckets with correct key schemes, ILM policies, and a storage client wrapper with presigned URL generation for direct client upload.

**Component Boundaries:**
- **Allowed:** `infra/buckets.sh`, `src/services/storage/`, `src/api/routes/presigned.py`, `tests/test_object_store.py`
- **Off-limits:** Bucket contents (audio, uploads, generated, exports), preprocessing workers (S17), ASR workers (S19)

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| MinIO | RELEASE.2024-xx | Object storage (S3-compatible) |
| boto3 | 1.35.x | S3 client for Python |
| mc (MinIO Client) | Latest | Bucket provisioning script |
| FastAPI | 0.141.1 | Presigned URL endpoint |

---

### 2. State Machine & Domain Schemas

**Bucket Key Schemes:**
```
lis-audio/       → {session_id}/chunks/{seq:05d}.opus    # ILM: 30 days post-complete
lis-uploads/     → {session_id}/{filename}                # Permanent
lis-generated/   → {session_id}/{asset_type}/{filename}   # Permanent
lis-exports/     → {session_id}/{export_id}.{ext}         # ILM: 7 days
lis-eval/        → phase0/v1/{session_id}/audio.opus      # Permanent, versioned via DVC
```

**ILM Policy Definitions:**
```json
{
  "Rules": [
    {
      "ID": "lis-audio-cleanup",
      "Status": "Enabled",
      "Filter": { "Prefix": "" },
      "Expiration": { "Days": 30 },
      "Tags": { "lifecycle": "post-complete" }
    }
  ]
}
```

**Pydantic Models:**
```python
# src/services/storage/models.py
from pydantic import BaseModel, Field
from enum import Enum
from uuid import UUID
from datetime import datetime


class BucketName(str, Enum):
    AUDIO = "lis-audio"
    UPLOADS = "lis-uploads"
    GENERATED = "lis-generated"
    EXPORTS = "lis-exports"
    EVAL = "lis-eval"


class PresignedURLRequest(BaseModel):
    session_id: UUID
    bucket: BucketName
    key: str = Field(..., description="Object key within bucket")
    expires_in: int = Field(default=3600, ge=60, le=86400, description="URL TTL in seconds")
    content_type: str | None = None


class PresignedURLResponse(BaseModel):
    upload_url: str
    key: str
    bucket: str
    expires_at: datetime


class ObjectMetadata(BaseModel):
    bucket: str
    key: str
    size: int
    etag: str
    last_modified: datetime
```

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Create `infra/buckets.sh` provisioning script | Script creates all 5 buckets |
| 2 | Configure ILM rules on `lis-audio` and `lis-exports` | `mc ilm ls` shows rules |
| 3 | Implement `StorageClient` wrapper with presigned URL generation | Unit tests pass |
| 4 | Create `POST /presigned-url` endpoint | `curl` returns valid URL |
| 5 | Verify presigned URL allows upload and expires | Upload succeeds, expired URL fails |
| 6 | Test key-scope isolation (cannot write outside scoped key) | Write to wrong key fails |
| 7 | Simulate ILM lifecycle evaluation | Audio objects flagged for deletion |

**Atomic Sub-tasks:**
1. Bucket provisioning script (`infra/buckets.sh`)
2. ILM policy configuration
3. `StorageClient` wrapper class
4. Presigned URL endpoint
5. Key-scope isolation enforcement
6. ILM lifecycle evaluation test

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| Bucket already exists | Idempotent creation — skip if present |
| Presigned URL expired | Return 403; client must request new URL |
| Write to wrong key prefix | Presigned URL scoped to specific key — reject |
| ILM rule not applied | Assert rule presence at provision time, not wait for expiry |
| MinIO unreachable | StorageClient raises `ConnectionError`; API returns 503 |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Repository pattern: `StorageClient` abstracts S3 operations
- Factory pattern: presigned URL generation per bucket type
- Configuration pattern: bucket names and ILM settings in config

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase
- Files: snake_case (`storage_client.py`, `presigned_url.py`)
- Constants: UPPER_SNAKE_CASE

**Code Splitting Metrics:**
- Max function length: 40 lines
- Max file length: 300 lines

**Type Safety:**
- All function signatures typed with Pydantic v2 models
- `from __future__ import annotations` in all files

---

### 5. API & Interface Contracts

**Presigned URL Endpoint:**
```yaml
POST /api/v1/presigned-url
Content-Type: application/json
Authorization: Bearer {token}

Request:
  session_id: "550e8400-e29b-41d4-a716-446655440000"
  bucket: "lis-audio"
  key: "550e8400-e29b-41d4-a716-446655440000/chunks/00001.opus"
  expires_in: 3600
  content_type: "audio/opus"

Response (200):
  upload_url: "http://minio:9000/lis-audio/550e8400.../chunks/00001.opus?X-Amz-Algorithm=..."
  key: "550e8400-e29b-41d4-a716-446655440000/chunks/00001.opus"
  bucket: "lis-audio"
  expires_at: "2026-09-12T11:00:00Z"
```

**Client Upload Using Presigned URL:**
```yaml
PUT {upload_url}
Content-Type: audio/opus
Body: <binary opus data>

Response: 200 OK
```

**StorageClient Interface:**
```python
# src/services/storage/client.py
class StorageClient:
    async def generate_presigned_upload(
        self,
        bucket: BucketName,
        key: str,
        expires_in: int = 3600,
        content_type: str | None = None,
    ) -> PresignedURLResponse:
        """Generate a presigned PUT URL for direct client upload."""

    async def put_object(
        self,
        bucket: BucketName,
        key: str,
        data: bytes,
        content_type: str | None = None,
    ) -> ObjectMetadata:
        """Upload object directly (server-side)."""

    async def get_object(
        self,
        bucket: BucketName,
        key: str,
    ) -> bytes:
        """Download object."""

    async def delete_object(
        self,
        bucket: BucketName,
        key: str,
    ) -> None:
        """Delete object."""

    async def list_objects(
        self,
        bucket: BucketName,
        prefix: str,
    ) -> list[ObjectMetadata]:
        """List objects under prefix."""
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Default |
|----------|------|-------------|---------|
| `MINIO_ENDPOINT` | string | MinIO endpoint | `minio:9000` |
| `MINIO_ACCESS_KEY` | string | MinIO access key | `minioadmin` |
| `MINIO_SECRET_KEY` | string | MinIO secret key | `changeme` |
| `MINIO_SECURE` | bool | Use TLS | `false` |
| `MINIO_AUDIO_BUCKET` | string | Audio chunks bucket | `lis-audio` |
| `MINIO_UPLOADS_BUCKET` | string | Client uploads bucket | `lis-uploads` |
| `MINIO_GENERATED_BUCKET` | string | Generated assets bucket | `lis-generated` |
| `MINIO_EXPORTS_BUCKET` | string | Export archives bucket | `lis-exports` |
| `MINIO_EVAL_BUCKET` | string | Eval data bucket | `lis-eval` |
| `PRESIGNED_URL_TTL_S` | int | Default presigned URL TTL | `3600` |

**Third-Party Integration Contracts:**
- MinIO: S3-compatible API (boto3 client)
- No external services required

**Version Pins:**
- boto3 >= 1.35.0
- mc client pinned in CI

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T14.1 | I | `pytest tests/test_object_store.py::test_round_trip_per_bucket -v` | Object round-trip per bucket with correct key scheme |
| T14.2 | I | `pytest tests/test_object_store.py::test_ilm_rule_present -v` | ILM rule present and correctly expressed on `lis-audio` |
| T14.3 | I | `pytest tests/test_object_store.py::test_presigned_put_and_expiry -v` | Presigned PUT allows upload; expires correctly; cannot be reused |
| T14.4 | S | `pytest tests/test_object_store.py::test_presigned_url_scoped_to_key -v` | Presigned URL scoped to one key, cannot write elsewhere |
| T14.5 | I | `pytest tests/test_object_store.py::test_audio_purge_leaves_transcripts -v` | Audio purge simulated leaves transcripts intact |

**Test Case Details (Given/When/Then):**

**T14.1 — Object round-trip per bucket with correct key scheme**
- **Given:** MinIO is running with all 5 buckets provisioned
- **When:** an object is PUT to each bucket using the correct key scheme
- **Then:** the object is retrievable at the same key, metadata matches

**T14.2 — ILM rule present and correctly expressed on lis-audio**
- **Given:** `lis-audio` bucket is provisioned with ILM rules
- **When:** `mc ilm ls local/lis-audio` is run
- **Then:** an expiration rule with 30-day TTL is present and enabled

**T14.3 — Presigned PUT allows upload and expires correctly**
- **Given:** a presigned PUT URL is generated with 60s TTL
- **When:** the URL is used to upload an object within TTL
- **Then:** upload succeeds; when reused after expiry, upload fails with 403

**T14.4 — Presigned URL scoped to one key**
- **Given:** a presigned PUT URL is generated for key `sess/chunks/00001.opus`
- **When:** the URL is used to PUT to a different key in the same bucket
- **Then:** the upload is rejected (SignatureDoesNotMatch)

**T14.5 — Audio purge simulated leaves transcripts intact**
- **Given:** audio objects exist in `lis-audio` and transcript data exists in `lis-generated`
- **When:** lifecycle evaluation is forced on `lis-audio`
- **Then:** audio objects are flagged for deletion; `lis-generated` objects remain untouched

**Verification Commands:**
```bash
# Provision buckets
bash infra/buckets.sh

# Run tests
uv run pytest tests/test_object_store.py -v -k "S14"

# Type check
uv run mypy --strict src/services/storage/

# Lint
uv run ruff check src/services/storage/
```

**Exit Criteria:**
- [ ] All 5 buckets provisioned with correct key schemes
- [ ] ILM rules enforced by policy (not cron job)
- [ ] Presigned URLs work for client direct upload
- [ ] Key-scope isolation enforced
- [ ] T14.1–T14.5 pass

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- ILM rules are policy-based, not cron-based — must be asserted at provision time
- Presigned URL scope must be enforced by including the full key in the signature — partial key prefixes allow escape
- MinIO `mc ilm ls` shows rules but does not enforce time-based expiry in dev mode — tests must assert rule presence, not wait for expiry
- `lis-eval` bucket is permanent and versioned via DVC — never apply ILM to it

**Fallback Instructions:**
- If MinIO is unreachable: StorageClient raises `ConnectionError`; API returns 503; retry with exponential backoff
- If ILM rule missing: re-provision with `mc ilm add`
- If presigned URL generation fails: check MinIO credentials and clock sync

**Rollback Procedure:**
- Remove ILM rules: `mc ilm rm local/lis-audio/<rule-id>`
- Delete buckets: `mc rb local/lis-audio` (only if empty)
- No database migrations — stateless infrastructure
- Feature flag: N/A (infrastructure only)

---

### 9. Observability (if applicable)

**Metrics Added:**
- `storage_presigned_url_total`: counter of presigned URLs generated (labels: bucket, success=true/false)
- `storage_upload_total`: counter of uploads (labels: bucket, method=server/presigned, success=true/false)
- `storage_upload_bytes`: histogram of upload sizes (labels: bucket)
- `storage_ilm_objects_flagged`: gauge of objects flagged for lifecycle evaluation

**Tracing/Logging:**
- Span: `storage.presigned_url` with attributes (bucket, key, expires_in)
- Span: `storage.upload` with attributes (bucket, key, size, method)
- Log: INFO on presigned URL generation
- Log: ERROR on upload failure with bucket, key, error details

**Alerts:**
- Presigned URL generation failure rate > 5%: MinIO connectivity issue
- Upload failure rate > 1%: storage backend issue

---

### 10. Exit Checklist

- [ ] All tests pass (T14.1, T14.2, T14.3, T14.4, T14.5)
- [ ] All 5 buckets provisioned: `lis-audio`, `lis-uploads`, `lis-generated`, `lis-exports`, `lis-eval`
- [ ] ILM policies enforced by policy, not cron
- [ ] Presigned URL endpoint functional
- [ ] Key-scope isolation verified
- [ ] StorageClient wrapper complete and tested
