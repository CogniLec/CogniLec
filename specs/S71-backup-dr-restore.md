# S71 — Backup, DR & Restore Drill
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Implement pgBackRest on both PostgreSQL instances (daily full backup, 15-minute WAL archiving, 30-day retention), restic for MinIO bucket contents, Healthchecks.io dead-man's-switch alerting when a backup doesn't run, and execute a documented restore drill proving the backup is real.

**Component Boundaries:**
- **Allowed:** `docker/compose/backup/`, `config/pgbackrest/`, `config/restic/`, `scripts/backup/`, `scripts/restore/`, `docs/runbooks/`, `tests/`
- **Off-limits:** Application source code, database schemas, agent logic, model serving code

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| pgBackRest | 2.53.x | PostgreSQL backup & PITR |
| restic | 0.17.x | Object store (MinIO) backup |
| Healthchecks.io | cloud/self-hosted | Dead-man's-switch alerting |
| PostgreSQL | 16.x | Database (both instances) |
| MinIO | latest | Object store |
| Docker Compose | 2.x | Deployment |

---

### 2. State Machine & Domain Schemas

**Backup Job Lifecycle:**
```
scheduled → running → completed → verified
                   → failed → (retry → running | alert)
```

**pgBackRest Configuration (`config/pgbackrest/pgbackrest.conf`):**
```ini
[global]
repo1-path=/backups/pgbackrest
repo1-retention-full=2
repo1-retention-diff=7
repo1-cipher-type=aes-256-cbc
repo1-cipher-pass=${PGBACKREST_CIPHER_PASS}
process-max=4
compress-type=zst
compress-level=6

[pg-main]
pg1-path=/var/lib/postgresql/data/main
pg1-port=5432

[pg-syllabus]
pg1-path=/var/lib/postgresql/data/syllabus
pg1-port=5433
```

**Backup Schedule:**
```
Daily full backup:    02:00 UTC
WAL archiving:        every 15 minutes (continuous)
Differential backup:  02:00 UTC on Wed/Sat (between full backups)
Object store backup:  03:00 UTC daily
Healthchecks.io ping: every 15 minutes (dead-man's-switch)
```

**Restic Repository Structure:**
```
minio-backup/
├── lis-data/
│   ├── audio/
│   ├── uploads/
│   └── generated/
└── metadata/
```

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Deploy pgBackRest container with shared volume for both PG instances | `pgbackrest --stanza=pg-main info` succeeds |
| 2 | Configure WAL archiving on PG-MAIN (`archive_mode=on`, `archive_command`) | WAL files appear in pgBackRest repo |
| 3 | Configure WAL archiving on PG-SYLLABUS | WAL files appear in pgBackRest repo |
| 4 | Run initial full backup on PG-MAIN | `pgbackrest --stanza=pg-main backup --type=full` succeeds; verify with `info` |
| 5 | Run initial full backup on PG-SYLLABUS | `pgbackrest --stanza=pg-syllabus backup --type=full` succeeds |
| 6 | Configure restic for MinIO bucket | `restic init` succeeds; `restic snapshots` returns empty list |
| 7 | Run initial restic backup of MinIO contents | `restic backup /data/minio` succeeds |
| 8 | Set up Healthchecks.io ping job | Ping URL configured; check shows "Up" |
| 9 | Configure backup scripts to ping Healthchecks.io on success and `fail` on no-ping | Dead-man's-switch alerting active |
| 10 | Test PITR: restore PG-MAIN to arbitrary timestamp | Database restored to correct state |
| 11 | Test full restore on clean host | System fully operational with all data |
| 12 | Document restore runbook | Runbook complete and tested |
| 13 | Execute restore drill with operator who didn't write the runbook | Drill passes |
| 14 | Test object-store restore | Audio, uploads, and generated images recovered |
| 15 | Run all T71.x tests | All pass |

**Atomic Sub-tasks:**
1. pgBackRest deployment and configuration for both PG instances
2. WAL archiving setup
3. Restic deployment for MinIO
4. Healthchecks.io dead-man's-switch configuration
5. PITR test execution
6. Full restore drill execution
7. Restore runbook documentation

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| WAL archiving fails | Alert fires; manual intervention required; WAL queue monitored |
| pgBackRest backup exceeds retention | Old backups pruned automatically per retention policy |
| Restic repository corrupted | `restic check --read-data` verifies integrity; restore from last known-good |
| Healthchecks.io ping not received | Dead-man's-switch alert fires within 2× check interval |
| Restore drill fails | Halt release; investigate and fix backup before proceeding |
| Disk space exhausted during backup | Alert fires; compress and prune old backups; expand volume |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Dead-man's-switch pattern (Healthchecks.io): absence of a ping = alert
- WAL-based continuous archiving for zero-data-loss PITR
- Encrypted backup repositories (AES-256-CBC)

**Naming & Style Guidelines:**
- Backup scripts: `scripts/backup/{stanza}_backup.sh`
- Restore scripts: `scripts/restore/{stanza}_restore.sh`
- Runbook: `docs/runbooks/restore-runbook.md`
- pgBackRest stanzas: `pg-main`, `pg-syllabus`

**Code Splitting Metrics:**
- Backup scripts: max 80 lines each
- Restore scripts: max 120 lines each (more complex)
- Runbook: max 500 lines

**Type Safety:**
- All backup/restore scripts use `set -euo pipefail`
- All PostgreSQL connections verified before backup start
- Exit codes propagated correctly

---

### 5. API & Interface Contracts

**pgBackRest Commands:**
```bash
# Full backup
pgbackrest --stanza=pg-main --type=full backup

# Differential backup
pgbackrest --stanza=pg-main --type=diff backup

# WAL archiving (called by PG archive_command)
pgbackrest --stanza=pg-main archive-push /path/to/wal_file

# PITR restore
pgbackrest --stanza=pg-main --target="2026-09-12 10:30:00+00" --type=time restore

# Verify backup
pgbackrest --stanza=pg-main info
pgbackrest --stanza=pg-main check
```

**Restic Commands:**
```bash
# Initialize repository
restic -r s3:s3.amazonaws.com/lis-backups init

# Backup
restic -r s3:s3.amazonaws.com/lis-backups backup /data/minio --exclude="*.tmp"

# Restore
restic -r s3:s3.amazonaws.com/lis-backups restore latest --target /data/minio-restore

# Verify
restic -r s3:s3.amazonaws.com/lis-backups check --read-data

# List snapshots
restic -r s3:s3.amazonaws.com/lis-backups snapshots
```

**Healthchecks.io Integration:**
```bash
# Ping on backup start
curl -m 10 -X POST https://hc-ping.com/${HEALTHCHECKS_IO_UUID}-backup-start

# Ping on backup success
curl -m 10 -X POST https://hc-ping.com/${HEALTHCHECKS_IO_UUID}-backup-success

# Fail (no-ping triggers alert)
# Simply don't ping; Healthchecks.io alerts after grace period
```

**Backup Verification Schema:**
```python
# Internal verification result (not a DB table)
class BackupVerificationResult(BaseModel):
    stanza: str  # pg-main, pg-syllabus, minio
    backup_type: str  # full, diff, wal, object
    backup_time: datetime
    backup_size_bytes: int
    verification_status: str  # passed, failed
    wal_range: tuple[str, str] | None = None  # for PG: (oldest_wal, newest_wal)
    pitr_test_timestamp: datetime | None = None
    pitr_test_result: str | None = None  # passed, failed
    errors: list[str] = []
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Example |
|----------|------|-------------|---------|
| `PGBACKREST_STANZA_MAIN` | string | pgBackRest stanza name for PG-MAIN | `pg-main` |
| `PGBACKREST_STANZA_SYLLABUS` | string | pgBackRest stanza name for PG-SYLLABUS | `pg-syllabus` |
| `PGBACKREST_CIPHER_PASS` | string | Encryption password for pgBackRest repos | `changeme-...` |
| `PGBACKREST_REPO1_PATH` | string | pgBackRest repo path | `/backups/pgbackrest` |
| `RESTIC_REPOSITORY` | string | Restic repo URL | `s3:s3.amazonaws.com/lis-backups` |
| `RESTIC_PASSWORD` | string | Restic repository password | `changeme-...` |
| `HEALTHCHECKS_IO_UUID` | string | Healthchecks.io ping UUID | `abc-123-def-456` |
| `HEALTHCHECKS_IO_URL` | string | Healthchecks.io base URL | `https://hc-ping.com` |
| `BACKUP_RETENTION_DAYS` | int | Retention period in days | `30` |
| `PITR_TEST_ENABLED` | bool | Enable automated PITR testing | `true` |

**Docker Compose Services:**
- `pgbackrest` (shared volume for both PG stanzas)
- `restic-cron` (daily restic backup container)
- `healthchecks-pinger` (cron-based ping)

**Volume Mounts:**
- `/backups/pgbackrest` — pgBackRest repository (persistent)
- `/data/minio` — MinIO data (shared with restic)
- `/var/lib/postgresql/data/main` — PG-MAIN data (shared with pgBackRest)
- `/var/lib/postgresql/data/syllabus` — PG-SYLLABUS data (shared with pgBackRest)

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Given | When | Then |
|---------|------|-------|------|------|
| T71.1 | I | Both PG instances configured with pgBackRest | Full backup runs on each | Backup completes; `pgbackrest info` shows valid backup set for both PG-MAIN and PG-SYLLABUS |
| T71.2 | I | WAL archiving active on PG-MAIN | Insert data; advance WAL; trigger PITR restore to post-insert timestamp | Restore succeeds; data present and consistent at the target timestamp |
| T71.3 | E | Full backup of both PG instances and MinIO exists | Restore to a completely clean host | System starts fully operational; all user data, sessions, notes, and objects present |
| T71.4 | I | Healthchecks.io ping configured for backup job | Suppress backup ping (don't run backup) | Dead-man's-switch alert fires within the configured grace period |
| T71.5 | I | Object-store backup of MinIO exists; audio and generated images uploaded | Restore from restic snapshot | Audio files, uploads, and generated images all recovered and accessible |
| T71.6 | M | Restore runbook documented; operator who didn't write it available | Operator follows runbook step by step | Restore completes successfully; operator confirms runbook is clear and complete |

**Verification Commands:**
```bash
# Verify pgBackRest info
pgbackrest --stanza=pg-main info
pgbackrest --stanza=pg-syllabus info

# Verify WAL archiving is active
psql -h localhost -p 5432 -U lis -d lis -c "SHOW archive_mode;"
psql -h localhost -p 5432 -U lis -d lis -c "SHOW archive_command;"

# Verify restic snapshots
restic -r $RESTIC_REPOSITORY snapshots

# Verify Healthchecks.io integration
curl -s https://hc-ping.com/$HEALTHCHECKS_IO_UUID | jq .

# Verify backup integrity
pgbackrest --stanza=pg-main check
restic -r $RESTIC_REPOSITORY check

# Full verification
docker compose -f docker/compose/backup/docker-compose.yml ps && \
pgbackrest --stanza=pg-main info && \
pgbackrest --stanza=pg-syllabus info && \
restic -r $RESTIC_REPOSITORY snapshots && \
curl -s https://hc-ping.com/$HEALTHCHECKS_IO_UUID | jq .
```

**Exit Criteria:**
- [ ] Full backup completes and is verifiable on both PG-MAIN and PG-SYLLABUS (T71.1)
- [ ] WAL archiving active; PITR to arbitrary timestamp succeeds (T71.2)
- [ ] Full restore to clean host reproduces working system (T71.3)
- [ ] Dead-man's-switch alert fires on suppressed backup (T71.4)
- [ ] Object-store restore recovers audio, uploads, generated images (T71.5)
- [ ] Restore runbook followed successfully by non-author (T71.6)

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- WAL archiving can fall behind if disk fills; monitor `archive_status` directory
- pgBackRest full backup on large databases may take hours; schedule during low-traffic window
- Restic snapshots can grow large; configure `prune` schedule
- Healthchecks.io free tier has limits; monitor ping count
- Restore drill on production data requires a clean test environment; don't restore over production
- Encrypted backups are useless without the cipher password; store securely (e.g., Vault)

**Fallback Instructions:**
- If pgBackRest fails, fall back to `pg_dump` manual backup
- If restic fails, fall back to `mc mirror` (MinIO client) for bucket copy
- If Healthchecks.io is unreachable, fall back to direct email alerting
- If PITR restore fails, restore from last full backup and re-apply WAL manually

**Rollback Procedure:**
- Backup infrastructure: `docker compose -f docker/compose/backup/docker-compose.yml down`
- pgBackRest config: revert `pgbackrest.conf` and restart PG instances
- Restic config: revert environment variables and restart restic container
- No application code changes; purely infrastructure rollback

---

### 9. Observability (if applicable)

**Metrics Added:**
- `lis_backup_last_success_timestamp{stanza,type}`: Gauge — timestamp of last successful backup
- `lis_backup_duration_seconds{stanza,type}`: Histogram — backup duration
- `lis_backup_size_bytes{stanza,type}`: Gauge — backup size
- `lis_backup_errors_total{stanza,type}`: Counter — backup failures
- `lis_wal_archiving_lag_seconds{stanza}`: Gauge — WAL archiving lag
- `lis_restic_snapshot_count`: Gauge — number of restic snapshots
- `lis_pitr_test_success_total`: Counter — PITR test results

**Tracing/Logging:**
- Span: `backup.pgbackrest_full` for full backup execution
- Span: `backup.pgbackrest_diff` for differential backup
- Span: `backup.restic` for object-store backup
- Span: `backup.pitr_test` for PITR test execution
- Log event: `backup_started` with stanza, backup_type
- Log event: `backup_completed` with stanza, backup_type, duration, size
- Log event: `backup_failed` with stanza, backup_type, error
- Log event: `pitr_test_result` with stanza, timestamp, result

**Alerts:**
- Alert if backup hasn't succeeded in 26 hours (daily backup overdue)
- Alert if WAL archiving lag > 1 hour
- Alert if restic snapshot count drops (pruning issue)
- Alert if PITR test fails
- Alert if backup duration exceeds 2× historical average

---

### 10. Exit Checklist

- [ ] All tests pass (T71.1, T71.2, T71.3, T71.4, T71.5, T71.6)
- [ ] Full backup completes on both PG instances
- [ ] WAL archiving active and PITR tested
- [ ] Full restore to clean host succeeds
- [ ] Dead-man's-switch alerting active
- [ ] Object-store restore recovers all data
- [ ] Restore runbook documented and tested by non-author
- [ ] Backup encryption verified
- [ ] Retention policy enforced
- [ ] Observability metrics and alerts configured
