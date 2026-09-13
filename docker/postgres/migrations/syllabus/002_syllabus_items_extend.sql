-- S50/S52 — DB-3: extend syllabus_items with hierarchy/coverage metadata,
-- and add the a6_writer role for DB-level write-authority enforcement
-- (FR-3.8). Applied out-of-band via scripts/s11_apply_syllabus_schema.py,
-- same as 001_syllabus_items.sql. Idempotent.
--
-- NOTE on write authority: the existing "lis" role (SYLLABUS_DATABASE_URL)
-- is the long-standing direct-write connection used across this repo's test
-- fixtures and out-of-band schema application (see s11_apply_syllabus_schema.py
-- and tests/conftest.py's syllabus_session fixture, both predating S50).
-- REVOKEing INSERT/UPDATE/DELETE from "lis" here would break that shared
-- infra outside S50's scope. We therefore add a6_writer as the role real
-- A6 write paths should authenticate as in a deployed environment, and
-- rely on the application-level DB3WriteGuard (src/db/write_guard.py) as
-- the enforced gate in this environment. This is a documented, deliberate
-- narrowing of FR-3.8's "GRANT only to a6_writer" requirement - see
-- docs/gaps.md gap #9.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'a6_writer') THEN
        CREATE ROLE a6_writer WITH LOGIN PASSWORD 'a6_writer_dev';
    END IF;
END
$$;

GRANT CONNECT ON DATABASE lis_syllabus TO a6_writer;
GRANT USAGE ON SCHEMA public TO a6_writer;
GRANT INSERT, UPDATE, DELETE, SELECT ON syllabus_items TO a6_writer;

ALTER TABLE syllabus_items
ADD COLUMN IF NOT EXISTS item_type VARCHAR(20) NOT NULL DEFAULT 'topic',
ADD COLUMN IF NOT EXISTS weight_pct DOUBLE PRECISION,
ADD COLUMN IF NOT EXISTS week_number INTEGER,
ADD COLUMN IF NOT EXISTS syllabus_references TEXT [] DEFAULT '{}',
ADD COLUMN IF NOT EXISTS manually_corrected BOOLEAN NOT NULL DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS alignment_confidence VARCHAR(20);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_syllabus_items_item_type'
    ) THEN
        ALTER TABLE syllabus_items
            ADD CONSTRAINT ck_syllabus_items_item_type CHECK (
                item_type IN ('module', 'topic', 'subtopic', 'assessment', 'reference', 'schedule')
            );
    END IF;
END
$$;

GRANT SELECT ON syllabus_items TO lis_fdw_reader;
