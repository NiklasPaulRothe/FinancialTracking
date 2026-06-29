-- =============================================================================
-- Migration: Add recurring_rule_tags association table
-- =============================================================================
-- Usage:
--   psql -U postgres -d haushaltsbuch -f sql/006_add_recurring_rule_tags.sql
-- =============================================================================

CREATE TABLE IF NOT EXISTS recurring_rule_tags (
    recurring_rule_id INTEGER NOT NULL REFERENCES recurring_rules(id),
    tag_id INTEGER NOT NULL REFERENCES tags(id),
    PRIMARY KEY (recurring_rule_id, tag_id)
);

-- =============================================================================
-- DONE
-- =============================================================================
