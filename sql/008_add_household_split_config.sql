-- =============================================================================
-- Migration: Add household split configuration to users table
-- =============================================================================
-- Usage:
--   psql -U postgres -d haushaltsbuch -f sql/008_add_household_split_config.sql
-- =============================================================================

ALTER TABLE users ADD COLUMN IF NOT EXISTS household_split_account_id INTEGER;
ALTER TABLE users ADD COLUMN IF NOT EXISTS household_split_tags VARCHAR(500);

-- =============================================================================
-- DONE
-- =============================================================================
