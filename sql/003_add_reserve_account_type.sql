-- =============================================================================
-- Migration: Add 'reserve' to account_type enum
-- Run against existing haushaltsbuch database
-- =============================================================================
-- Usage:
--   psql -U postgres -d haushaltsbuch -f sql/003_add_reserve_account_type.sql
-- =============================================================================

ALTER TYPE account_type ADD VALUE IF NOT EXISTS 'reserve' AFTER 'saving';

-- =============================================================================
-- DONE
-- =============================================================================
