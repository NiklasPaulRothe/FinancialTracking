-- =============================================================================
-- Migration: Add due_date and paid columns to transactions table
-- For credit card transactions without statement cycle
-- =============================================================================
-- Usage:
--   psql -U postgres -d haushaltsbuch -f sql/004_add_credit_card_due_date.sql
-- =============================================================================

ALTER TABLE transactions ADD COLUMN IF NOT EXISTS due_date DATE;
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS paid BOOLEAN NOT NULL DEFAULT FALSE;

-- Set existing credit card transactions as paid (historic data)
UPDATE transactions SET paid = TRUE WHERE type = 'credit_card_payment';

-- =============================================================================
-- DONE
-- =============================================================================
