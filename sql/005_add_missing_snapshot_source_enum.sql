-- =============================================================================
-- Migration: Create snapshot_source enum type if missing
-- =============================================================================
-- Usage:
--   psql -U postgres -d haushaltsbuch -f sql/005_add_missing_snapshot_source_enum.sql
-- =============================================================================

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'snapshot_source') THEN
        CREATE TYPE snapshot_source AS ENUM ('automatic', 'manual');
    END IF;
END
$$;

-- =============================================================================
-- DONE
-- =============================================================================
