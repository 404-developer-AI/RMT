-- =============================================================================
-- RMT — local development database bootstrap
-- =============================================================================
-- Creates the `rmt_dev` role and database on your local PostgreSQL instance.
-- Run once, as the `postgres` superuser, supplying a password of your choice:
--
--     psql -U postgres -v password='your-dev-password' -f scripts/dev/create-db.sql
--
-- Then mirror the same password in your local `.env`:
--
--     DATABASE_URL=postgresql+asyncpg://rmt_dev:your-dev-password@localhost:5432/rmt_dev
--
-- Idempotent: safe to re-run; existing role/database are left untouched.
-- =============================================================================

\set ON_ERROR_STOP on

-- Create the role if it does not already exist.
-- `\gexec` runs the SELECT's result as a SQL statement, which lets us use the
-- psql `:'password'` variable substitution outside of a dollar-quoted block.
SELECT 'CREATE ROLE rmt_dev WITH LOGIN PASSWORD ' || quote_literal(:'password') AS stmt
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rmt_dev')
\gexec

-- Create the database if it does not already exist.
SELECT 'CREATE DATABASE rmt_dev OWNER rmt_dev ENCODING ''UTF8'''
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'rmt_dev')
\gexec

-- Dedicated database for the pytest suite so tests can truncate rows
-- freely without nuking the dev DB's configured credentials / migrations.
-- The backend picks it up automatically in APP_ENV=testing (see conftest.py).
SELECT 'CREATE DATABASE rmt_dev_test OWNER rmt_dev ENCODING ''UTF8'''
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'rmt_dev_test')
\gexec

GRANT ALL PRIVILEGES ON DATABASE rmt_dev TO rmt_dev;
GRANT ALL PRIVILEGES ON DATABASE rmt_dev_test TO rmt_dev;
