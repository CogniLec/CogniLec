-- PostgreSQL MAIN Initialization
-- Runs on first container startup

-- Dedicated database for MLflow's own backend store. It must not share
-- lis_main: MLflow runs its own Alembic migrations against a default
-- "alembic_version" table, which collides with the app's own Alembic
-- state if both live in the same database.
CREATE DATABASE mlflow OWNER lis;

-- Dedicated database for the pytest integration suite (tests/conftest.py).
-- Previously the test suite's `DROP SCHEMA public CASCADE` ran directly
-- against lis_main -- the SAME database the live app/API uses -- so every
-- test run silently wiped real registered users/subjects/everything else.
-- tests/conftest.py now points DATABASE_URL at lis_test instead; lis_main
-- is never touched by a test run again.
CREATE DATABASE lis_test OWNER lis;

-- Create extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp"; -- noqa: RF05
CREATE EXTENSION IF NOT EXISTS citext;

-- Grant permissions
GRANT USAGE ON SCHEMA public TO lis;
GRANT CREATE ON SCHEMA public TO lis;
GRANT ALL PRIVILEGES ON DATABASE lis_main TO lis;
GRANT ALL PRIVILEGES ON DATABASE lis_test TO lis;

-- Create schemas for partitioning
CREATE SCHEMA IF NOT EXISTS partitions AUTHORIZATION lis;

-- Set search path
ALTER DATABASE lis_main SET search_path TO public, partitions, pg_catalog; -- noqa: PRS,LT05
