-- =============================================================================
-- Migration: Add saving_goal_id to recurring_rules table
-- =============================================================================
-- Usage:
--   psql -U postgres -d haushaltsbuch -f sql/009_add_saving_goal_to_recurring.sql
-- =============================================================================

ALTER TABLE recurring_rules ADD COLUMN IF NOT EXISTS saving_goal_id INTEGER REFERENCES saving_goals(id);

-- =============================================================================
-- DONE
-- =============================================================================
