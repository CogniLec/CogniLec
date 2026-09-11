# ADR-013: Row-Level Security for Data Isolation

## Status
Accepted

## Context
Multi-user system (FR-6.5). Data isolation must survive application bugs.
Application-layer checks are insufficient (SQL injection, bypass).

## Decision
PostgreSQL Row-Level Security (RLS) on all user-data tables:
- `users`, `subjects`, `sessions`, `utterances`, `segments`, `note_sections`, `note_provenance`, `note_assets`
- Policy: `WHERE subject_id IN (SELECT id FROM subjects WHERE user_id = current_setting('app.user_id'))`
- Repository layer sets `SET LOCAL app.user_id = $1` per request
- Missing `app.user_id` → zero rows (fail-closed)
- JWT auth via fastapi-users (Argon2id passwords)

## Consequences
- Isolation enforced by PostgreSQL, not application code
- Direct SQL queries also blocked (T12.1, T12.2)
- Single-user pilot scope initially
- Argon2id password hashing (never plaintext)

## Follow-up
- S12: RLS policies + auth stub
- S13: Test harness verifies RLS
- S24: Transcript API respects RLS
