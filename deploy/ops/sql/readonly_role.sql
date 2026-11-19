-- Read-only role for the operations console.
--
-- Run as a database superuser, for example:
--   psql "postgresql://cece:<password>@172.25.18.172:15432/<database>"
--
-- Adjust these three names before running:
--   database : the DeerFlow database (confirm with SELECT current_database())
--   schema   : database.postgres_schema from config.yaml (dev172 uses deerflow)
--   password : a NEW password, not the superuser password
--
-- Re-running this file is safe.

-- 1) Create the login role once.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ops_readonly') THEN
        CREATE ROLE ops_readonly LOGIN;
    END IF;
END
$$;

ALTER ROLE ops_readonly PASSWORD 'CHANGE_ME';
ALTER ROLE ops_readonly SET default_transaction_read_only = on;
ALTER ROLE ops_readonly SET statement_timeout = '5s';
ALTER ROLE ops_readonly SET idle_in_transaction_session_timeout = '10s';

-- 2) Allow connecting and reading the four tables the console needs.
--    schema = deerflow for the CECE deployments; use public for a stock setup.
GRANT CONNECT ON DATABASE deerflow TO ops_readonly;
GRANT USAGE ON SCHEMA deerflow TO ops_readonly;
GRANT SELECT ON deerflow.users, deerflow.threads_meta, deerflow.runs, deerflow.run_events TO ops_readonly;

-- 3) Verify the role cannot write:
--   SET ROLE ops_readonly;
--   SELECT count(*) FROM deerflow.runs;          -- works
--   DELETE FROM deerflow.runs WHERE false;       -- ERROR: cannot execute DELETE
--   RESET ROLE;