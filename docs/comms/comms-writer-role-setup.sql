-- comms_writer Postgres role for editorial publishing.
--
-- Why: src/comms/publishing.py:publish_editorial_post() must SELECT, INSERT,
-- and UPDATE rows on editorial_posts (rotation check + idempotent claim row
-- + telegram_message_id backfill). Granting it the full app DATABASE_URL is
-- overkill; this role is the least-privilege handle the publishing runtime should use.
--
-- Editorial tooling may receive ANALYST_DATABASE_URL for read-only analysis and
-- DATABASE_URL for the narrow publishing write path. DATABASE_URL must NOT be
-- mapped to ANALYST_DATABASE_URL or to the full app FFMEMES_DATABASE_URL.
-- Run this once on prod against the ff database as a superuser. After this,
-- configure the publishing runtime secret:
--   DATABASE_URL=postgresql+asyncpg://comms_writer:<password>@<host>:<port>/ff
-- (use the asyncpg driver — src/database.py builds an async engine).
--
-- Tracking: FFM-919.

\set ON_ERROR_STOP on

-- 1. Create the role if it does not exist. Replace the password before run.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'comms_writer') THEN
        CREATE ROLE comms_writer WITH LOGIN PASSWORD 'CHANGE_ME_BEFORE_RUNNING';
    END IF;
END
$$;

-- 2. Connect + schema usage.
GRANT CONNECT ON DATABASE ff TO comms_writer;
GRANT USAGE ON SCHEMA public TO comms_writer;

-- 3. Table grants — editorial_posts only. SELECT is required for the rotation
--    check and the draft_hash idempotency lookup; INSERT/UPDATE for the claim
--    row + telegram_message_id backfill.
GRANT SELECT, INSERT, UPDATE ON TABLE public.editorial_posts TO comms_writer;

-- 4. Identity column needs sequence usage to allow new id allocation on INSERT.
--    The sequence is implicitly created by the IDENTITY column; resolve and
--    grant explicitly so future schema migrations don't drop access.
DO $$
DECLARE
    seq_name text;
BEGIN
    SELECT pg_get_serial_sequence('public.editorial_posts', 'id') INTO seq_name;
    IF seq_name IS NULL THEN
        RAISE EXCEPTION 'editorial_posts.id has no associated sequence';
    END IF;
    EXECUTE format('GRANT USAGE, SELECT ON SEQUENCE %s TO comms_writer', seq_name);
END
$$;

-- 5. Defensive: short statement timeout so a runaway query in the Comms env
--    cannot hold a connection forever. The publishing flow is point-lookup
--    and small inserts — 10s is plenty.
ALTER ROLE comms_writer SET statement_timeout = '10s';

-- 6. Sanity: list grants for the role so the operator can eyeball them.
SELECT grantee, privilege_type, table_name
FROM information_schema.table_privileges
WHERE grantee = 'comms_writer'
ORDER BY table_name, privilege_type;
