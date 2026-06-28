-- =============================================================================
-- Migration: Add starting_balance column to accounts table
-- Run against existing haushaltsbuch database
-- =============================================================================
-- Usage:
--   psql -U postgres -d haushaltsbuch -f sql/002_add_starting_balance.sql
-- =============================================================================

-- Add the starting_balance column with default 0.00
ALTER TABLE accounts
    ADD COLUMN IF NOT EXISTS starting_balance NUMERIC(12,2) NOT NULL DEFAULT 0.00;

-- Set starting_balance to current balance for existing accounts
-- (assumes existing accounts were created with their current balance as the starting point)
UPDATE accounts SET starting_balance = balance WHERE starting_balance = 0.00 AND balance != 0.00;

-- =============================================================================
-- DONE
-- =============================================================================
