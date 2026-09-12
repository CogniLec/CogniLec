# S75 — Corpus Reprocessing & Re-Clustering Operations
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Implement scheduled overnight reprocessing of stored sessions with current models and prompts so existing notes improve retroactively, operator tooling for full subject re-cluster, partition merge/split with audit logging (FR-5.13), and promote embedding-version backfill to a first-class operation.

**Component Boundaries:**
- **Allowed:** `src/flows/reprocessing/`, `src/operators/`, `config/reprocessing/`, `scripts/recluster/`, `tests/`
- **Off-limits:** Core agent logic, model training code, database schema changes, auth code

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| Prefect | 2.x | Workflow orchestration |
| SQLAlchemy | 2.0.52 | ORM |
| asyncpg | 0.31.0 | PG driver |
| Pydantic | 2.13.5 | Validation |
| FastAPI | 0.141.1 | Operator API |

---

### 2. State Machine & Domain Schemas

**Reprocessing Job Lifecycle:**
```
scheduled -> queued -> running -> completed -> verified
                          -> failed -> (retry -> running | alert)
```

**Re-cluster Job Lifecycle:**
```
requested -> validating -> running -> completed -> audit_logged
                              -> failed -> (rollback | alert)
```

**Partition Merge/Split Lifecycle:**
```
requested -> validated -> executing -> completed -> audit_logged
                             -> failed -> (rollback -> audit_logged)
```

**Audit Log Schema:**
```python
class ClusterAuditLog(Base):
    __tablename__ = "cluster_audit_log"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, server_default=text("gen_random_uuid()"))
    operation: Mapped[str] = mapped_column(String(50), nullable=False)  # recluster, merge, split, backfill
    subject_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    initiated_by: Mapped[str] = mapped_column(String(255), nullable=False)
    before_state: Mapped[dict] = mapped_column(JSONB, nullable=False)  # partition count, topic count, etc.
    after_state: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # running, completed, failed, rolled_back
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "operation IN ('recluster', 'merge', 'split', 'backfill')",
            name="ck_audit_operation"
        ),
        CheckConstraint(
            "status IN ('running', 'completed', 'failed', 'rolled_back')",
            name="ck_audit_status"
        ),
    )
```

**Reprocessing Configuration:**
```yaml
# config/reprocessing/overnight.yaml
reprocessing:
  schedule: "0 2 * * *"  # 02:00 UTC daily
  max_sessions_per_run: 100
  batch_size: 10
  timeout_per_session_s: 300
  models:
    - agent: "A1"
      prompt_version: "current"
    - agent: "A2"
      prompt_version: "current"
    - agent: "A4"
      prompt_version: "current"
  skip_if:
    - user_edited: true  # preserve user edits
    - prompt_version_already_current: true
```

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Create `cluster_audit_log` table migration | `alembic upgrade head` succeeds |
| 2 | Implement overnight reprocessing flow in Prefect | Flow registered; can be triggered manually |
| 3 | Implement user-edit preservation logic | User edits not overwritten during reprocessing |
| 4 | Implement full subject re-cluster operator tooling | API endpoints functional |
| 5 | Implement partition merge with audit logging | Merge recorded in audit log with before/after state |
| 6 | Implement partition split with audit logging | Split recorded in audit log with before/after state |
| 7 | Implement merge reversal from audit record | Rollback from audit log successful |
| 8 | Implement embedding-version backfill as first-class operation | Backfill runbook complete |
| 9 | Schedule overnight reprocessing via Prefect | Cron schedule active |
| 10 | Test reprocessing with newer prompt version | Notes updated without duplication |
| 11 | Test user-edit preservation | User edits preserved |
| 12 | Test re-cluster with user-edited topic labels | Labels preserved |
| 13 | Test overnight reprocessing of 100 sessions | Completes within window |
| 14 | Evaluate reprocessed note quality | Equal or better than originals |
| 15 | Run all T75.x tests | All pass |

**Atomic Sub-tasks:**
1. Audit log table and migration
2. Overnight reprocessing flow
3. User-edit preservation logic
4. Re-cluster operator tooling
5. Partition merge/split with audit logging
6. Merge reversal from audit record
7. Embedding-version backfill
8. Quality evaluation

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| Reprocessing produces worse notes | Skip that session; log warning; alert operator |
| User edit conflicts with reprocessed content | Preserve user edit; log conflict |
| Re-cluster changes topic boundaries | Preserve user-edited labels; reassign unedited labels |
| Merge cannot be reversed | Log warning; require manual intervention |
| Backfill fails mid-way | Resume from checkpoint; log partial completion |
| Overnight job exceeds time window | Stop at window end; resume next night |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Operator pattern (API-driven operations with audit logging)
- Saga pattern (multi-step operations with compensating actions)
- Checkpoint pattern (resumable long-running operations)
- Audit trail pattern (immutable log of all mutations)

**Naming & Style Guidelines:**
- Reprocessing flows: `src/flows/reprocessing/`
- Operator API: `src/api/routes/operators.py`
- Audit models: `src/db/models/cluster_audit.py`
- Config: `config/reprocessing/`
- Scripts: `scripts/recluster/`

**Code Splitting Metrics:**
- Max function length: 40 lines
- Max file length: 300 lines
- Reprocessing flow: separate from core pipeline
- Operator tooling: separate from user-facing API

**Type Safety:**
- All function signatures must have type hints
- Audit log state captured as typed Pydantic models
- Reprocessing config validated with strict schemas

---

### 5. API & Interface Contracts

**Operator API Endpoints:**
```
POST   /api/v1/operators/recluster/{subject_id}      -> 202 ReclusterResponse
POST   /api/v1/operators/merge                        -> 202 MergeResponse
POST   /api/v1/operators/split                        -> 202 SplitResponse
POST   /api/v1/operators/backfill                     -> 202 BackfillResponse
POST   /api/v1/operators/reprocess                    -> 202 ReprocessResponse

GET    /api/v1/operators/audit-log                    -> 200 list[AuditLogResponse]
GET    /api/v1/operators/audit-log/{id}               -> 200 AuditLogResponse
POST   /api/v1/operators/audit-log/{id}/rollback      -> 202 RollbackResponse
```

**Request/Response Payloads:**
```json
// POST /api/v1/operators/recluster/{subject_id}
// Response 202:
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "subject_id": "550e8400-e29b-41d4-a716-446655440001",
  "status": "queued",
  "estimated_duration_s": 600,
  "created_at": "2026-09-12T02:00:00Z"
}

// POST /api/v1/operators/merge
// Request:
{
  "subject_id": "550e8400-e29b-41d4-a716-446655440001",
  "partition_ids": ["partition-a", "partition-b"],
  "target_partition_name": "merged-topic"
}
// Response 202:
{
  "job_id": "660e8400-e29b-41d4-a716-446655440001",
  "status": "queued",
  "audit_log_id": "770e8400-e29b-41d4-a716-446655440001"
}

// POST /api/v1/operators/split
// Request:
{
  "subject_id": "550e8400-e29b-41d4-a716-446655440001",
  "partition_id": "partition-to-split",
  "split_criteria": "topic_boundary"
}
// Response 202:
{
  "job_id": "880e8400-e29b-41d4-a716-446655440001",
  "status": "queued",
  "audit_log_id": "990e8400-e29b-41d4-a716-446655440001"
}

// GET /api/v1/operators/audit-log
// Response 200:
{
  "items": [
    {
      "id": "770e8400-e29b-41d4-a716-446655440001",
      "operation": "merge",
      "subject_id": "550e8400-e29b-41d4-a716-446655440001",
      "initiated_by": "admin@university.edu",
      "before_state": {"partition_count": 5, "topic_count": 12},
      "after_state": {"partition_count": 4, "topic_count": 11},
      "status": "completed",
      "duration_s": 45.2,
      "created_at": "2026-09-12T02:10:00Z",
      "completed_at": "2026-09-12T02:10:45Z"
    }
  ],
  "total": 1
}
```

**Reprocessing Flow (Prefect):**
```python
# src/flows/reprocessing/overnight.py
@flow(name="overnight-reprocessing", retries=1, retry_delay_seconds=300)
def overnight_reprocessing(config: ReprocessingConfig):
    sessions = get_sessions_for_reprocessing(config)
    for batch in chunk(sessions, config.batch_size):
        batch_results = process_batch(batch, config)
        log_batch_results(batch_results)
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Example |
|----------|------|-------------|---------|
| `DATABASE_URL` | string | PG-MAIN connection | `postgresql+asyncpg://localhost:5432/lis` |
| `SYLLABUS_DATABASE_URL` | string | PG-SYLLABUS connection | `postgresql+asyncpg://localhost:5432/lis_syllabus` |
| `REPROCESSING_SCHEDULE` | string | Cron schedule for overnight reprocessing | `0 2 * * *` |
| `REPROCESSING_MAX_SESSIONS` | int | Max sessions per reprocessing run | `100` |
| `REPROCESSING_BATCH_SIZE` | int | Batch size for reprocessing | `10` |
| `REPROCESSING_TIMEOUT_S` | int | Timeout per session | `300` |
| `CLUSTER_AUDIT_LOG_RETENTION_DAYS` | int | Audit log retention | `365` |
| `PREFECT_API_URL` | string | Prefect server URL | `http://prefect:4200/api` |

**Third-Party Integration Contracts:**
- Prefect: Workflow orchestration for reprocessing and re-cluster jobs
- MinIO: Object store for reprocessed session audio

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Given | When | Then |
|---------|------|-------|------|------|
| T75.1 | I | Session processed with prompt_version v1; v2 available | Reprocessing runs with v2 | Notes updated with v2 content; no duplication of sections |
| T75.2 | I | Session with user edits (S65 corrections applied) | Reprocessing runs with newer prompt | User edits preserved; reprocessed content incorporates corrections |
| T75.3 | I | Subject with user-edited topic labels (S31) | Full subject re-cluster runs | User-edited topic labels preserved; unedited labels may change |
| T75.4 | I | Partition merge and split operations available | Execute merge then split | Both operations recorded in audit log with before/after state |
| T75.5 | I | Completed merge in audit log | Rollback requested from audit record | Merge reversed; audit log updated with rolled_back status |
| T75.6 | P | 100 sessions needing reprocessing | Overnight reprocessing scheduled | All 100 sessions processed within the time window |
| T75.7 | V | Reprocessed notes available; human evaluators ready | Sample of 20 reprocessed sessions evaluated | Reprocessed notes rated equal or better than originals (human sample) |

**Verification Commands:**
```bash
# Verify audit log table exists
psql -h localhost -p 5432 -U lis -d lis -c "\d cluster_audit_log"

# Verify reprocessing flow registered
prefect flow-runs list --flow-name overnight-reprocessing

# Verify re-cluster endpoint
curl -X POST http://localhost:8000/api/v1/operators/recluster/{subject_id} -H "Authorization: Bearer $TOKEN"

# Verify audit log
curl http://localhost:8000/api/v1/operators/audit-log -H "Authorization: Bearer $TOKEN" | jq .

# Full verification
uv run pytest tests/ -m integration -v -k "S75 or reprocessing or recluster or audit_log"
```

**Exit Criteria:**
- [ ] Reprocessing with newer prompt produces updated notes without duplication (T75.1)
- [ ] Reprocessing preserves user edits and corrections (T75.2)
- [ ] Full subject re-cluster preserves user-edited topic labels (T75.3)
- [ ] Partition merge and split both recorded in audit log (T75.4)
- [ ] Merge can be reversed from audit record (T75.5)
- [ ] Overnight reprocessing of 100 sessions completes within window (T75.6)
- [ ] Reprocessed notes rated equal or better than originals (T75.7)

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- Reprocessing with newer prompts may produce inconsistent quality; require human review
- User-edit preservation requires tracking edit provenance; if edit metadata lost, cannot preserve
- Re-cluster may change topic boundaries unpredictably; always preserve user-edited labels
- Merge reversal may not be perfect if data has changed since merge; log warnings
- Overnight reprocessing may compete with live serving for GPU resources; use training windows (S74)

**Fallback Instructions:**
- If reprocessing produces worse notes, skip that session and alert operator
- If user edit preservation fails, preserve original notes and log conflict
- If re-cluster changes too many boundaries, revert to previous state from audit log
- If overnight job exceeds window, stop and resume next night

**Rollback Procedure:**
- Reprocessing: revert notes to pre-reprocessing state using audit log checkpoint
- Re-cluster: revert to previous partition state from audit log
- Merge: execute rollback from audit log (`POST /api/v1/operators/audit-log/{id}/rollback`)
- Split: execute rollback from audit log
- Backfill: revert to previous embedding version

---

### 9. Observability (if applicable)

**Metrics Added:**
- `lis_reprocessing_sessions_total`: Counter of sessions reprocessed
- `lis_reprocessing_duration_s`: Histogram of reprocessing duration per session
- `lis_reprocessing_quality_delta`: Gauge of quality change (reprocessed vs original)
- `lis_recluster_jobs_total{status}`: Counter of re-cluster jobs
- `lis_recluster_duration_s`: Histogram of re-cluster duration
- `lis_partition_merge_total`: Counter of partition merges
- `lis_partition_split_total`: Counter of partition splits
- `lis_audit_log_entries_total{operation}`: Counter of audit log entries

**Tracing/Logging:**
- Span: `reprocessing.session` for individual session reprocessing
- Span: `reprocessing.batch` for batch processing
- Span: `recluster.subject` for full subject re-cluster
- Span: `partition.merge` for partition merge
- Span: `partition.split` for partition split
- Log event: `reprocessing_started` with session_count, prompt_version
- Log event: `reprocessing_completed` with session_count, success_count, fail_count
- Log event: `user_edit_preserved` with session_id, edit_type
- Log event: `audit_log_created` with operation, subject_id

**Alerts:**
- Alert if reprocessing quality degrades (reprocessed < original)
- Alert if overnight reprocessing exceeds time window
- Alert if re-cluster changes > 50% of topic boundaries
- Alert if merge rollback fails
- Alert if audit log write fails

---

### 10. Exit Checklist

- [ ] All tests pass (T75.1, T75.2, T75.3, T75.4, T75.5, T75.6, T75.7)
- [ ] Corpus improves as system improves
- [ ] User contributions preserved during reprocessing
- [ ] Audit log captures all partition mutations
- [ ] Merge can be reversed from audit record
- [ ] Overnight reprocessing completes within time window
- [ ] Reprocessed notes quality-evaluated and acceptable
- [ ] Embedding-version backfill is first-class operation
- [ ] Observability metrics and alerts configured
