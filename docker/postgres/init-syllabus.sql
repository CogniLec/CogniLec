-- PostgreSQL SYLLABUS Initialization
-- Runs on first container startup

-- Dedicated database for the pytest integration suite (tests/conftest.py).
-- Previously the test suite's `DROP SCHEMA public CASCADE` ran directly
-- against lis_syllabus -- the SAME database the live app uses -- so every
-- test run silently wiped real syllabus data. tests/conftest.py now
-- points SYLLABUS_DATABASE_URL at lis_syllabus_test instead.
CREATE DATABASE lis_syllabus_test OWNER lis;

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp"; -- noqa: RF05
CREATE EXTENSION IF NOT EXISTS citext;

GRANT USAGE ON SCHEMA public TO lis;
GRANT CREATE ON SCHEMA public TO lis;
GRANT ALL PRIVILEGES ON DATABASE lis_syllabus TO lis;
GRANT ALL PRIVILEGES ON DATABASE lis_syllabus_test TO lis;

ALTER DATABASE lis_syllabus SET search_path TO public, pg_catalog; -- noqa: PRS
