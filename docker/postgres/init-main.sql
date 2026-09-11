-- PostgreSQL MAIN Initialization
-- Runs on first container startup

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
