-- PostgreSQL SYLLABUS Initialization
-- Runs on first container startup

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp"; -- noqa: RF05
CREATE EXTENSION IF NOT EXISTS citext;

GRANT USAGE ON SCHEMA public TO lis;
GRANT CREATE ON SCHEMA public TO lis;
GRANT ALL PRIVILEGES ON DATABASE lis_syllabus TO lis;

ALTER DATABASE lis_syllabus SET search_path TO public, pg_catalog; -- noqa: PRS
