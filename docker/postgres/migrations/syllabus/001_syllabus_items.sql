-- S11 — DB-3: Syllabus Instance schema
-- Applied directly to PG-SYLLABUS (lis_syllabus). Alembic (src/db/migrations/)
-- only targets PG-MAIN, so this file is the source of truth for the
-- syllabus_items table and is applied out-of-band via
-- scripts/s11_apply_syllabus_schema.py. It is idempotent (safe to re-run).
--
-- See specs/S11-db3-syllabus-fdw.md section 2 for the authoritative schema.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS syllabus_items (
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

CREATE INDEX IF NOT EXISTS idx_syllabus_subject ON syllabus_items(subject_id);
CREATE INDEX IF NOT EXISTS idx_syllabus_parent ON syllabus_items(parent_id);

-- S11 T11.5: dedicated read-only role for the PG-MAIN FDW user mapping.
-- REVOKE/GRANT on the local foreign table has no effect on its owner
-- ("lis", which also owns the direct-write connection), so read-only
-- enforcement has to happen on THIS (remote) side instead: the FDW user
-- mapping authenticates as this restricted role, which only ever has
-- SELECT on syllabus_items - never the write-capable "lis" role.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'lis_fdw_reader') THEN
        CREATE ROLE lis_fdw_reader LOGIN PASSWORD 'lis_fdw_reader_dev';
    END IF;
END
$$;

GRANT CONNECT ON DATABASE lis_syllabus TO lis_fdw_reader;
GRANT USAGE ON SCHEMA public TO lis_fdw_reader;
GRANT SELECT ON syllabus_items TO lis_fdw_reader;
REVOKE INSERT, UPDATE, DELETE ON syllabus_items FROM lis_fdw_reader;
