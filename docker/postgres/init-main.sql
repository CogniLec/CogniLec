-- PostgreSQL MAIN Initialization
-- Runs on first container startup

-- Dedicated database for MLflow's own backend store. It must not share
-- lis_main: MLflow runs its own Alembic migrations against a default
-- "alembic_version" table, which collides with the app's own Alembic
-- state if both live in the same database, and lis_main's schema is
-- dropped/recreated by the integration test suite between runs.
CREATE DATABASE mlflow OWNER lis;

-- Create extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp"; -- noqa: RF05
CREATE EXTENSION IF NOT EXISTS citext;

-- Grant permissions
GRANT USAGE ON SCHEMA public TO lis;
GRANT CREATE ON SCHEMA public TO lis;
GRANT ALL PRIVILEGES ON DATABASE lis_main TO lis;

-- Create schemas for partitioning
CREATE SCHEMA IF NOT EXISTS partitions AUTHORIZATION lis;

-- Set search path
ALTER DATABASE lis_main SET search_path TO public, partitions, pg_catalog;
