# ADR-004: Dual PostgreSQL Instances with FDW

## Status
Accepted

## Context
Syllabus data (DB-3) must be separate from main data (DB-1/DB-2):
- Different backup/recovery policies
- Different access patterns (read-heavy, hierarchical)
- Different schema evolution
- FDW allows joins from main DB

## Decision
Two PostgreSQL 17 instances:
- **PG-MAIN** (lis_main): pgvector, pg_partman, pg_cron, all app data
- **PG-SYLLABUS** (lis_syllabus): syllabus_items hierarchy only
- **FDW** on PG-MAIN: postgres_fdw server + user mapping + foreign table
- FDW user mapping: read-only from PG-MAIN side

## Consequences
- True isolation at infrastructure level
- Cross-DB joins possible but explicit
- FDW failure = graceful degradation (not hang)
- Separate connection pooling (PgBouncer per instance)

## Follow-up
- S03: Compose stack with both instances
- S11: FDW setup and read-through repository
- S13: Test harness with both DBs
