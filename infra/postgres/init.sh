#!/bin/sh
# Creates the database roles and both databases. Runs once, on an empty data directory.
#   voiceops_owner  owns the schema; used only for migrations and loading demo data
#   voiceops_app    API and workers; not a table owner, so row-level security always applies
set -e
psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" <<SQL
CREATE ROLE voiceops_owner LOGIN PASSWORD '${VOICEOPS_OWNER_PASSWORD:-voiceops_owner}';
CREATE ROLE voiceops_app   LOGIN PASSWORD '${VOICEOPS_APP_PASSWORD:-voiceops_app}';
CREATE DATABASE voiceops      OWNER voiceops_owner;
CREATE DATABASE voiceops_test OWNER voiceops_owner;
SQL
for db in voiceops voiceops_test; do
psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$db" <<SQL
CREATE EXTENSION IF NOT EXISTS pg_trgm;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO voiceops_app;
ALTER DEFAULT PRIVILEGES FOR ROLE voiceops_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO voiceops_app;
ALTER DEFAULT PRIVILEGES FOR ROLE voiceops_owner IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO voiceops_app;
SQL
done
