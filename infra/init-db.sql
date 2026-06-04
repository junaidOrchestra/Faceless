-- Creates the two independent databases used by the two services in local dev.
-- pgvector is installed per-database by each service's migrations.sql.
CREATE DATABASE clip;
CREATE DATABASE orchestrator;
