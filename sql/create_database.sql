-- =============================================================================
-- Haushaltsbuch Schema Creation Script
-- PostgreSQL 15+
-- Assumes: database "haushaltsbuch" already exists, connected as postgres
-- =============================================================================
-- Usage:
--   psql -U postgres -d haushaltsbuch -f sql/create_database.sql
-- =============================================================================

-- =============================================================================
-- ENUM TYPES
-- =============================================================================

CREATE TYPE account_type AS ENUM ('spending', 'saving', 'credit_card');
CREATE TYPE account_scope AS ENUM ('personal', 'shared');
CREATE TYPE snapshot_source AS ENUM ('automatic', 'manual');
CREATE TYPE transaction_type AS ENUM ('income', 'expense', 'transfer', 'credit_card_payment');
CREATE TYPE transaction_scope AS ENUM ('personal', 'shared');
CREATE TYPE recurring_frequency AS ENUM ('daily', 'weekly', 'monthly', 'quarterly', 'yearly');
CREATE TYPE budget_scope AS ENUM ('personal', 'shared');
CREATE TYPE budget_period AS ENUM ('weekly', 'monthly', 'quarterly', 'yearly');
CREATE TYPE saving_goal_scope AS ENUM ('personal', 'shared');
CREATE TYPE saving_goal_status AS ENUM ('active', 'completed', 'cancelled');
CREATE TYPE planned_expense_scope AS ENUM ('personal', 'shared');
CREATE TYPE credit_status AS ENUM ('active', 'paid_off');
CREATE TYPE credit_scope AS ENUM ('personal', 'shared');
CREATE TYPE etf_transaction_type AS ENUM ('buy', 'sell');
CREATE TYPE bav_type AS ENUM ('direktversicherung', 'pensionskasse', 'pensionsfonds', 'direktzusage', 'unterstuetzungskasse');
CREATE TYPE audit_action AS ENUM ('create', 'update', 'delete');

-- =============================================================================
-- TABLES
-- =============================================================================

-- ---------------------------------------------------------------------------
-- users
-- ---------------------------------------------------------------------------
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(30) NOT NULL,
    email VARCHAR(255) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    income_day INTEGER NOT NULL,
    date_format VARCHAR(10) NOT NULL DEFAULT 'DD.MM.YYYY',
    marginal_tax_rate NUMERIC(5,4) NOT NULL DEFAULT 0.0,
    social_security_rate NUMERIC(5,4) NOT NULL DEFAULT 0.0,
    assumed_annual_return NUMERIC(5,4) NOT NULL DEFAULT 0.07,
    target_retirement_age INTEGER NOT NULL DEFAULT 67,
    created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),

    CONSTRAINT ck_users_income_day_range CHECK (income_day >= 1 AND income_day <= 31),
    CONSTRAINT ck_users_marginal_tax_rate_range CHECK (marginal_tax_rate >= 0.0 AND marginal_tax_rate <= 1.0),
    CONSTRAINT ck_users_social_security_rate_range CHECK (social_security_rate >= 0.0 AND social_security_rate <= 1.0)
);

CREATE UNIQUE INDEX ix_users_username ON users (username);
CREATE UNIQUE INDEX ix_users_email ON users (email);

-- ---------------------------------------------------------------------------
-- accounts
-- ---------------------------------------------------------------------------
CREATE TABLE accounts (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) NOT NULL,
    type account_type NOT NULL,
    scope account_scope NOT NULL,
    balance NUMERIC(12,2) NOT NULL DEFAULT 0.0,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    institute VARCHAR(100),
    visible_to_partner BOOLEAN NOT NULL DEFAULT TRUE,
    max_overdraft NUMERIC(12,2),
    credit_limit NUMERIC(12,2),
    statement_closing_day INTEGER,
    payment_due_day INTEGER,
    owner_id INTEGER NOT NULL REFERENCES users(id),
    created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),

    CONSTRAINT ck_accounts_credit_limit_range CHECK (credit_limit IS NULL OR (credit_limit >= 0.01 AND credit_limit <= 999999999.99)),
    CONSTRAINT ck_accounts_statement_closing_day_range CHECK (statement_closing_day IS NULL OR (statement_closing_day >= 1 AND statement_closing_day <= 28)),
    CONSTRAINT ck_accounts_payment_due_day_range CHECK (payment_due_day IS NULL OR (payment_due_day >= 1 AND payment_due_day <= 28))
);

-- ---------------------------------------------------------------------------
-- account_owners
-- ---------------------------------------------------------------------------
CREATE TABLE account_owners (
    id SERIAL PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),

    CONSTRAINT uq_account_owners_account_user UNIQUE (account_id, user_id)
);

-- ---------------------------------------------------------------------------
-- account_balance_snapshots
-- ---------------------------------------------------------------------------
CREATE TABLE account_balance_snapshots (
    id SERIAL PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    balance NUMERIC(12,2) NOT NULL,
    snapshot_date DATE NOT NULL,
    source snapshot_source NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc')
);

-- ---------------------------------------------------------------------------
-- categories
-- ---------------------------------------------------------------------------
CREATE TABLE categories (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) NOT NULL,
    scope VARCHAR(10) NOT NULL,
    icon VARCHAR(50),
    user_id INTEGER NOT NULL REFERENCES users(id),

    CONSTRAINT uq_categories_name_user_scope UNIQUE (name, user_id, scope)
);

-- ---------------------------------------------------------------------------
-- tags
-- ---------------------------------------------------------------------------
CREATE TABLE tags (
    id SERIAL PRIMARY KEY,
    name VARCHAR(30) NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id),

    CONSTRAINT uq_tags_name_user UNIQUE (name, user_id)
);

-- ---------------------------------------------------------------------------
-- recurring_rules
-- ---------------------------------------------------------------------------
CREATE TABLE recurring_rules (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    type transaction_type NOT NULL,
    frequency recurring_frequency NOT NULL,
    "interval" INTEGER NOT NULL,
    amount NUMERIC(12,2) NOT NULL,
    next_due_date DATE NOT NULL,
    end_date DATE,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    scope transaction_scope NOT NULL,
    account_id INTEGER REFERENCES accounts(id),
    destination_account_id INTEGER REFERENCES accounts(id),
    category_id INTEGER REFERENCES categories(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),

    CONSTRAINT ck_recurring_rules_interval_range CHECK ("interval" >= 1 AND "interval" <= 365),
    CONSTRAINT ck_recurring_rules_amount_range CHECK (amount >= 0.01 AND amount <= 999999999.99)
);

-- ---------------------------------------------------------------------------
-- recurring_rule_splits
-- ---------------------------------------------------------------------------
CREATE TABLE recurring_rule_splits (
    id SERIAL PRIMARY KEY,
    recurring_rule_id INTEGER NOT NULL REFERENCES recurring_rules(id),
    category_id INTEGER NOT NULL REFERENCES categories(id),
    amount NUMERIC(12,2) NOT NULL,
    description VARCHAR(255),

    CONSTRAINT ck_recurring_rule_splits_amount_positive CHECK (amount > 0)
);

-- ---------------------------------------------------------------------------
-- transactions
-- ---------------------------------------------------------------------------
CREATE TABLE transactions (
    id SERIAL PRIMARY KEY,
    type transaction_type NOT NULL,
    amount NUMERIC(12,2) NOT NULL,
    date DATE NOT NULL,
    description VARCHAR(255),
    scope transaction_scope NOT NULL,
    account_id INTEGER REFERENCES accounts(id),
    destination_account_id INTEGER REFERENCES accounts(id),
    category_id INTEGER REFERENCES categories(id),
    recurring_rule_id INTEGER REFERENCES recurring_rules(id),
    posted BOOLEAN NOT NULL DEFAULT TRUE,
    statement_closing_date DATE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),

    CONSTRAINT ck_transactions_amount_range CHECK (amount >= 0.01 AND amount <= 999999999.99)
);

-- ---------------------------------------------------------------------------
-- transaction_splits
-- ---------------------------------------------------------------------------
CREATE TABLE transaction_splits (
    id SERIAL PRIMARY KEY,
    transaction_id INTEGER NOT NULL REFERENCES transactions(id),
    category_id INTEGER NOT NULL REFERENCES categories(id),
    amount NUMERIC(12,2) NOT NULL,
    description VARCHAR(255),

    CONSTRAINT ck_transaction_splits_amount_positive CHECK (amount > 0)
);

-- ---------------------------------------------------------------------------
-- transaction_tags (association table)
-- ---------------------------------------------------------------------------
CREATE TABLE transaction_tags (
    transaction_id INTEGER NOT NULL REFERENCES transactions(id),
    tag_id INTEGER NOT NULL REFERENCES tags(id),
    PRIMARY KEY (transaction_id, tag_id)
);

-- ---------------------------------------------------------------------------
-- planned_expenses
-- ---------------------------------------------------------------------------
CREATE TABLE planned_expenses (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    amount_exact NUMERIC(12,2),
    amount_min NUMERIC(12,2),
    amount_max NUMERIC(12,2),
    category_id INTEGER REFERENCES categories(id),
    scope planned_expense_scope NOT NULL,
    account_id INTEGER REFERENCES accounts(id),
    blocking BOOLEAN NOT NULL DEFAULT TRUE,
    note VARCHAR(255),
    resolved BOOLEAN NOT NULL DEFAULT FALSE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    amount_from_range BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),

    CONSTRAINT ck_planned_expenses_amount_exact_range CHECK (amount_exact IS NULL OR (amount_exact >= 0.01 AND amount_exact <= 999999999.99)),
    CONSTRAINT ck_planned_expenses_amount_min_range CHECK (amount_min IS NULL OR (amount_min >= 0.01 AND amount_min <= 999999999.99)),
    CONSTRAINT ck_planned_expenses_amount_max_range CHECK (amount_max IS NULL OR (amount_max >= 0.01 AND amount_max <= 999999999.99))
);

-- ---------------------------------------------------------------------------
-- transaction_planned_expenses
-- ---------------------------------------------------------------------------
CREATE TABLE transaction_planned_expenses (
    id SERIAL PRIMARY KEY,
    transaction_id INTEGER NOT NULL REFERENCES transactions(id),
    planned_expense_id INTEGER NOT NULL REFERENCES planned_expenses(id),
    resolved_amount NUMERIC(12,2) NOT NULL
);

-- ---------------------------------------------------------------------------
-- shared_expenses
-- ---------------------------------------------------------------------------
CREATE TABLE shared_expenses (
    id SERIAL PRIMARY KEY,
    transaction_id INTEGER NOT NULL REFERENCES transactions(id),
    paid_by_user_id INTEGER NOT NULL REFERENCES users(id),
    total_amount NUMERIC(12,2) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc')
);

-- ---------------------------------------------------------------------------
-- shared_expense_shares
-- ---------------------------------------------------------------------------
CREATE TABLE shared_expense_shares (
    id SERIAL PRIMARY KEY,
    shared_expense_id INTEGER NOT NULL REFERENCES shared_expenses(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    amount NUMERIC(12,2) NOT NULL,
    share_percentage NUMERIC(5,4) NOT NULL,
    settled BOOLEAN NOT NULL DEFAULT FALSE,
    settled_at TIMESTAMP
);

-- ---------------------------------------------------------------------------
-- settlements
-- ---------------------------------------------------------------------------
CREATE TABLE settlements (
    id SERIAL PRIMARY KEY,
    amount NUMERIC(12,2) NOT NULL,
    date DATE NOT NULL,
    from_user_id INTEGER NOT NULL REFERENCES users(id),
    to_user_id INTEGER NOT NULL REFERENCES users(id),
    created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),

    CONSTRAINT ck_settlements_amount_range CHECK (amount >= 0.01 AND amount <= 999999999.99),
    CONSTRAINT ck_settlements_different_users CHECK (from_user_id != to_user_id)
);

-- ---------------------------------------------------------------------------
-- settlement_allocations
-- ---------------------------------------------------------------------------
CREATE TABLE settlement_allocations (
    id SERIAL PRIMARY KEY,
    settlement_id INTEGER NOT NULL REFERENCES settlements(id),
    shared_expense_share_id INTEGER NOT NULL REFERENCES shared_expense_shares(id),
    amount NUMERIC(12,2) NOT NULL
);

-- ---------------------------------------------------------------------------
-- budgets
-- ---------------------------------------------------------------------------
CREATE TABLE budgets (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    scope budget_scope NOT NULL,
    category_id INTEGER REFERENCES categories(id),
    amount NUMERIC(12,2) NOT NULL,
    period budget_period NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    reference_user_id INTEGER REFERENCES users(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),

    CONSTRAINT ck_budgets_amount_range CHECK (amount >= 0.01 AND amount <= 999999999.99)
);

-- ---------------------------------------------------------------------------
-- saving_goals
-- ---------------------------------------------------------------------------
CREATE TABLE saving_goals (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description VARCHAR(255),
    target_amount NUMERIC(12,2),
    scope saving_goal_scope NOT NULL,
    status saving_goal_status NOT NULL DEFAULT 'active',
    user_id INTEGER NOT NULL REFERENCES users(id),
    completed_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),

    CONSTRAINT ck_saving_goals_target_amount_range CHECK (target_amount IS NULL OR (target_amount >= 0.01 AND target_amount <= 999999999.99))
);

-- ---------------------------------------------------------------------------
-- saving_contributions
-- ---------------------------------------------------------------------------
CREATE TABLE saving_contributions (
    id SERIAL PRIMARY KEY,
    saving_goal_id INTEGER NOT NULL REFERENCES saving_goals(id),
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    amount NUMERIC(12,2) NOT NULL,
    note VARCHAR(255),
    user_id INTEGER NOT NULL REFERENCES users(id),
    created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),

    CONSTRAINT ck_saving_contributions_amount_range CHECK (amount >= 0.01 AND amount <= 999999999.99)
);

-- ---------------------------------------------------------------------------
-- credits
-- ---------------------------------------------------------------------------
CREATE TABLE credits (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    principal NUMERIC(12,2) NOT NULL,
    remaining_balance NUMERIC(12,2) NOT NULL,
    accrued_interest NUMERIC(12,6) NOT NULL DEFAULT 0.000000,
    effective_yearly_rate NUMERIC(7,6) NOT NULL,
    disbursement_date DATE NOT NULL,
    interest_capitalization_day INTEGER NOT NULL,
    status credit_status NOT NULL DEFAULT 'active',
    scope credit_scope NOT NULL,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    converted_from_credit_card_payment BOOLEAN NOT NULL DEFAULT FALSE,
    linked_transaction_id INTEGER REFERENCES transactions(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),

    CONSTRAINT ck_credits_principal_range CHECK (principal >= 0.01 AND principal <= 999999999.99),
    CONSTRAINT ck_credits_rate_range CHECK (effective_yearly_rate >= 0.0 AND effective_yearly_rate <= 1.0),
    CONSTRAINT ck_credits_capitalization_day_range CHECK (interest_capitalization_day >= 1 AND interest_capitalization_day <= 28)
);

-- ---------------------------------------------------------------------------
-- credit_payments
-- ---------------------------------------------------------------------------
CREATE TABLE credit_payments (
    id SERIAL PRIMARY KEY,
    credit_id INTEGER NOT NULL REFERENCES credits(id),
    transaction_id INTEGER NOT NULL REFERENCES transactions(id),
    total_amount NUMERIC(12,2) NOT NULL,
    interest_portion NUMERIC(12,2) NOT NULL,
    principal_portion NUMERIC(12,2) NOT NULL,
    manual_correction BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc')
);

-- ---------------------------------------------------------------------------
-- credit_forecast_cache
-- ---------------------------------------------------------------------------
CREATE TABLE credit_forecast_cache (
    id SERIAL PRIMARY KEY,
    credit_id INTEGER NOT NULL REFERENCES credits(id),
    month_offset INTEGER NOT NULL,
    projected_balance NUMERIC(12,2) NOT NULL,
    projected_interest NUMERIC(12,2) NOT NULL,
    recalculated_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc')
);

-- ---------------------------------------------------------------------------
-- credit_repayment_schedules
-- ---------------------------------------------------------------------------
CREATE TABLE credit_repayment_schedules (
    id SERIAL PRIMARY KEY,
    credit_id INTEGER NOT NULL REFERENCES credits(id),
    recurring_rule_id INTEGER NOT NULL REFERENCES recurring_rules(id),
    payment_amount NUMERIC(12,2) NOT NULL,
    note VARCHAR(255),
    created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),

    CONSTRAINT ck_credit_repayment_schedules_amount_range CHECK (payment_amount >= 0.01 AND payment_amount <= 999999999.99)
);

-- ---------------------------------------------------------------------------
-- investment_portfolios
-- ---------------------------------------------------------------------------
CREATE TABLE investment_portfolios (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    scope VARCHAR(10) NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id),
    target_retirement_age INTEGER,
    assumed_annual_return NUMERIC(5,4) DEFAULT 0.07,
    monthly_contribution_target NUMERIC(12,2),
    created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc')
);

-- ---------------------------------------------------------------------------
-- investment_portfolio_owners
-- ---------------------------------------------------------------------------
CREATE TABLE investment_portfolio_owners (
    id SERIAL PRIMARY KEY,
    portfolio_id INTEGER NOT NULL REFERENCES investment_portfolios(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),

    CONSTRAINT uq_investment_portfolio_owners_portfolio_user UNIQUE (portfolio_id, user_id)
);

-- ---------------------------------------------------------------------------
-- etf_positions
-- ---------------------------------------------------------------------------
CREATE TABLE etf_positions (
    id SERIAL PRIMARY KEY,
    portfolio_id INTEGER REFERENCES investment_portfolios(id),
    isin VARCHAR(12),
    ticker VARCHAR(10) NOT NULL,
    exchange_suffix VARCHAR(10) NOT NULL,
    name VARCHAR(200) NOT NULL,
    shares NUMERIC(12,6) NOT NULL DEFAULT 0.000000,
    average_buy_price NUMERIC(12,6) NOT NULL DEFAULT 0.000000,
    current_price NUMERIC(12,4),
    current_price_updated_at TIMESTAMP,
    manual_price_override BOOLEAN NOT NULL DEFAULT FALSE,
    consecutive_fetch_failures INTEGER NOT NULL DEFAULT 0,
    user_id INTEGER NOT NULL REFERENCES users(id),
    created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),

    CONSTRAINT ck_etf_positions_shares_non_negative CHECK (shares >= 0),
    CONSTRAINT ck_etf_positions_avg_price_non_negative CHECK (average_buy_price >= 0)
);

-- ---------------------------------------------------------------------------
-- etf_transactions
-- ---------------------------------------------------------------------------
CREATE TABLE etf_transactions (
    id SERIAL PRIMARY KEY,
    position_id INTEGER NOT NULL REFERENCES etf_positions(id),
    type etf_transaction_type NOT NULL,
    shares_quantity NUMERIC(12,6) NOT NULL,
    price_per_share NUMERIC(12,6) NOT NULL,
    total_amount NUMERIC(12,2) NOT NULL,
    fee NUMERIC(12,2) NOT NULL DEFAULT 0.00,
    note VARCHAR(255),
    linked_account_id INTEGER REFERENCES accounts(id),
    recurring_rule_id INTEGER REFERENCES recurring_rules(id),
    date DATE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id),
    created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),

    CONSTRAINT ck_etf_transactions_shares_positive CHECK (shares_quantity > 0),
    CONSTRAINT ck_etf_transactions_price_positive CHECK (price_per_share > 0)
);

-- ---------------------------------------------------------------------------
-- etf_price_history
-- ---------------------------------------------------------------------------
CREATE TABLE etf_price_history (
    id SERIAL PRIMARY KEY,
    position_id INTEGER NOT NULL REFERENCES etf_positions(id),
    price NUMERIC(12,4) NOT NULL,
    date DATE NOT NULL,

    CONSTRAINT uq_etf_price_history_position_date UNIQUE (position_id, date)
);

-- ---------------------------------------------------------------------------
-- etf_savings_plans
-- ---------------------------------------------------------------------------
CREATE TABLE etf_savings_plans (
    id SERIAL PRIMARY KEY,
    position_id INTEGER NOT NULL REFERENCES etf_positions(id),
    recurring_rule_id INTEGER NOT NULL REFERENCES recurring_rules(id),
    linked_account_id INTEGER NOT NULL REFERENCES accounts(id),
    shares_per_execution NUMERIC(12,6),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc')
);

-- ---------------------------------------------------------------------------
-- bavs (Betriebliche Altersvorsorge)
-- ---------------------------------------------------------------------------
CREATE TABLE bavs (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    provider VARCHAR(100) NOT NULL,
    contract_number VARCHAR(100),
    type bav_type NOT NULL,
    start_date DATE NOT NULL,
    retirement_date DATE,
    employee_contribution_monthly NUMERIC(10,2) NOT NULL,
    employer_contribution_monthly NUMERIC(10,2) NOT NULL DEFAULT 0.00,
    total_contribution_monthly NUMERIC(10,2) NOT NULL,
    guaranteed_payout_monthly NUMERIC(10,2),
    projected_payout_monthly NUMERIC(10,2),
    current_value NUMERIC(12,2),
    current_value_updated_at DATE,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),

    CONSTRAINT ck_bavs_employee_contribution_range CHECK (employee_contribution_monthly >= 0.01 AND employee_contribution_monthly <= 50000.00),
    CONSTRAINT ck_bavs_employer_contribution_range CHECK (employer_contribution_monthly >= 0.00 AND employer_contribution_monthly <= 50000.00)
);

-- ---------------------------------------------------------------------------
-- bav_contribution_logs
-- ---------------------------------------------------------------------------
CREATE TABLE bav_contribution_logs (
    id SERIAL PRIMARY KEY,
    bav_id INTEGER NOT NULL REFERENCES bavs(id),
    month DATE NOT NULL,
    employee_amount NUMERIC(10,2) NOT NULL,
    employer_amount NUMERIC(10,2) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),

    CONSTRAINT uq_bav_contribution_logs_bav_month UNIQUE (bav_id, month)
);

-- ---------------------------------------------------------------------------
-- vls (Vermögenswirksame Leistungen)
-- ---------------------------------------------------------------------------
CREATE TABLE vls (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    provider VARCHAR(100),
    contract_number VARCHAR(100),
    employer_contribution_monthly NUMERIC(10,2) NOT NULL,
    employee_contribution_monthly NUMERIC(10,2) NOT NULL DEFAULT 0.00,
    total_contribution_monthly NUMERIC(10,2) NOT NULL,
    start_date DATE NOT NULL,
    lock_up_end_date DATE NOT NULL,
    etf_position_id INTEGER REFERENCES etf_positions(id),
    linked_account_id INTEGER REFERENCES accounts(id),
    qualifies_for_sparzulage BOOLEAN NOT NULL DEFAULT FALSE,
    sparzulage_rate NUMERIC(5,4) NOT NULL DEFAULT 0.20,
    annual_eligible_max NUMERIC(10,2) NOT NULL DEFAULT 400.00,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc')
);

-- ---------------------------------------------------------------------------
-- vl_contribution_logs
-- ---------------------------------------------------------------------------
CREATE TABLE vl_contribution_logs (
    id SERIAL PRIMARY KEY,
    vl_id INTEGER NOT NULL REFERENCES vls(id),
    month DATE NOT NULL,
    employer_amount NUMERIC(10,2) NOT NULL,
    employee_amount NUMERIC(10,2) NOT NULL DEFAULT 0.00,
    amount NUMERIC(10,2) NOT NULL,
    shares_bought NUMERIC(12,6),
    price_per_share NUMERIC(12,6),
    note VARCHAR(255),
    etf_transaction_id INTEGER REFERENCES etf_transactions(id),
    created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),

    CONSTRAINT uq_vl_contribution_logs_vl_month UNIQUE (vl_id, month)
);

-- ---------------------------------------------------------------------------
-- notifications
-- ---------------------------------------------------------------------------
CREATE TABLE notifications (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    type VARCHAR(50) NOT NULL,
    entity_id INTEGER,
    message VARCHAR(500) NOT NULL,
    read BOOLEAN NOT NULL DEFAULT FALSE,
    link_url VARCHAR(255),
    created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc')
);

CREATE INDEX ix_notifications_user_id ON notifications (user_id);
CREATE INDEX ix_notifications_type ON notifications (type);

-- ---------------------------------------------------------------------------
-- notification_preferences
-- ---------------------------------------------------------------------------
CREATE TABLE notification_preferences (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    notification_type VARCHAR(50) NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),

    CONSTRAINT uq_notification_preferences_user_type UNIQUE (user_id, notification_type)
);

-- ---------------------------------------------------------------------------
-- import_column_mappings
-- ---------------------------------------------------------------------------
CREATE TABLE import_column_mappings (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    bank_name VARCHAR(100),
    date_column INTEGER NOT NULL,
    amount_column INTEGER NOT NULL,
    description_column INTEGER,
    date_format VARCHAR(20) NOT NULL,
    delimiter VARCHAR(1) NOT NULL,
    decimal_separator VARCHAR(1) NOT NULL,
    encoding VARCHAR(20) NOT NULL DEFAULT 'utf-8',
    skip_header_rows INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),
    updated_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),

    CONSTRAINT uq_import_column_mappings_account_bank UNIQUE (account_id, bank_name)
);

-- ---------------------------------------------------------------------------
-- import_logs
-- ---------------------------------------------------------------------------
CREATE TABLE import_logs (
    id SERIAL PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    filename VARCHAR(255) NOT NULL,
    total_rows INTEGER NOT NULL,
    imported_rows INTEGER NOT NULL,
    skipped_rows INTEGER NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id),
    created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc')
);

-- ---------------------------------------------------------------------------
-- net_worth_snapshots
-- ---------------------------------------------------------------------------
CREATE TABLE net_worth_snapshots (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    total_account_balance NUMERIC(14,2) NOT NULL DEFAULT 0.00,
    total_etf_value NUMERIC(14,2) NOT NULL DEFAULT 0.00,
    total_credit_balance NUMERIC(14,2) NOT NULL DEFAULT 0.00,
    total_value NUMERIC(14,2) NOT NULL,
    snapshot_date DATE NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),

    CONSTRAINT uq_net_worth_snapshots_user_date UNIQUE (user_id, snapshot_date)
);

-- ---------------------------------------------------------------------------
-- audit_logs
-- ---------------------------------------------------------------------------
CREATE TABLE audit_logs (
    id BIGSERIAL PRIMARY KEY,
    action audit_action NOT NULL,
    model VARCHAR(50) NOT NULL,
    record_id INTEGER NOT NULL,
    old_values JSONB,
    new_values JSONB,
    user_id INTEGER REFERENCES users(id),
    created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc')
);

CREATE INDEX ix_audit_logs_created_at ON audit_logs (created_at);
CREATE INDEX ix_audit_logs_model_record ON audit_logs (model, record_id);
CREATE INDEX ix_audit_logs_user_id ON audit_logs (user_id);

-- =============================================================================
-- APScheduler Job Store (required by Flask-APScheduler with SQLAlchemy job store)
-- =============================================================================
CREATE TABLE apscheduler_jobs (
    id VARCHAR(191) PRIMARY KEY,
    next_run_time DOUBLE PRECISION,
    job_state BYTEA NOT NULL
);

CREATE INDEX ix_apscheduler_jobs_next_run_time ON apscheduler_jobs (next_run_time);

-- =============================================================================
-- Alembic version tracking (used by Flask-Migrate)
-- =============================================================================
CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL,
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- =============================================================================
-- DONE
-- =============================================================================
