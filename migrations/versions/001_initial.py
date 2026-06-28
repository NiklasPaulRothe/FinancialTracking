"""Initial migration - create all tables.

Revision ID: 001_initial
Revises: None
Create Date: 2024-01-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- users ---
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(30), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("income_day", sa.Integer(), nullable=False),
        sa.Column("date_format", sa.String(10), nullable=False, server_default="DD.MM.YYYY"),
        sa.Column("marginal_tax_rate", sa.Numeric(5, 4), nullable=False, server_default="0.0"),
        sa.Column("social_security_rate", sa.Numeric(5, 4), nullable=False, server_default="0.0"),
        sa.Column("assumed_annual_return", sa.Numeric(5, 4), nullable=False, server_default="0.07"),
        sa.Column("target_retirement_age", sa.Integer(), nullable=False, server_default="67"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("income_day >= 1 AND income_day <= 31", name="ck_users_income_day_range"),
        sa.CheckConstraint("marginal_tax_rate >= 0.0 AND marginal_tax_rate <= 1.0", name="ck_users_marginal_tax_rate_range"),
        sa.CheckConstraint("social_security_rate >= 0.0 AND social_security_rate <= 1.0", name="ck_users_social_security_rate_range"),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # --- accounts ---
    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("type", sa.Enum("spending", "saving", "credit_card", name="accounttype"), nullable=False),
        sa.Column("scope", sa.Enum("personal", "shared", name="accountscope"), nullable=False),
        sa.Column("balance", sa.Numeric(12, 2), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("institute", sa.String(100), nullable=True),
        sa.Column("visible_to_partner", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("max_overdraft", sa.Numeric(12, 2), nullable=True),
        sa.Column("credit_limit", sa.Numeric(12, 2), nullable=True),
        sa.Column("statement_closing_day", sa.Integer(), nullable=True),
        sa.Column("payment_due_day", sa.Integer(), nullable=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "credit_limit IS NULL OR (credit_limit >= 0.01 AND credit_limit <= 999999999.99)",
            name="ck_accounts_credit_limit_range",
        ),
        sa.CheckConstraint(
            "statement_closing_day IS NULL OR (statement_closing_day >= 1 AND statement_closing_day <= 28)",
            name="ck_accounts_statement_closing_day_range",
        ),
        sa.CheckConstraint(
            "payment_due_day IS NULL OR (payment_due_day >= 1 AND payment_due_day <= 28)",
            name="ck_accounts_payment_due_day_range",
        ),
    )

    # --- account_owners ---
    op.create_table(
        "account_owners",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("account_id", "user_id", name="uq_account_owners_account_user"),
    )

    # --- account_balance_snapshots ---
    op.create_table(
        "account_balance_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("balance", sa.Numeric(12, 2), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("source", sa.Enum("automatic", "manual", name="snapshotsource"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    # --- categories ---
    op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("scope", sa.String(10), nullable=False),
        sa.Column("icon", sa.String(50), nullable=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.UniqueConstraint("name", "user_id", "scope", name="uq_categories_name_user_scope"),
    )

    # --- tags ---
    op.create_table(
        "tags",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(30), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.UniqueConstraint("name", "user_id", name="uq_tags_name_user"),
    )

    # --- recurring_rules ---
    op.create_table(
        "recurring_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("type", sa.Enum("income", "expense", "transfer", "credit_card_payment", name="transactiontype"), nullable=False),
        sa.Column("frequency", sa.Enum("daily", "weekly", "monthly", "quarterly", "yearly", name="recurringfrequency"), nullable=False),
        sa.Column("interval", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("next_due_date", sa.Date(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("scope", sa.Enum("personal", "shared", name="transactionscope"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("destination_account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=True),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("categories.id"), nullable=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint('"interval" >= 1 AND "interval" <= 365', name="ck_recurring_rules_interval_range"),
        sa.CheckConstraint("amount >= 0.01 AND amount <= 999999999.99", name="ck_recurring_rules_amount_range"),
    )

    # --- recurring_rule_splits ---
    op.create_table(
        "recurring_rule_splits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("recurring_rule_id", sa.Integer(), sa.ForeignKey("recurring_rules.id"), nullable=False),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("categories.id"), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.CheckConstraint("amount > 0", name="ck_recurring_rule_splits_amount_positive"),
    )

    # --- planned_expenses ---
    op.create_table(
        "planned_expenses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("amount_exact", sa.Numeric(12, 2), nullable=True),
        sa.Column("amount_min", sa.Numeric(12, 2), nullable=True),
        sa.Column("amount_max", sa.Numeric(12, 2), nullable=True),
        sa.Column("scope", sa.Enum("personal", "shared", name="plannedexpensescope"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=True),
        sa.Column("blocking", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("amount_from_range", sa.Boolean(), nullable=False, server_default="false"),
        sa.CheckConstraint(
            "amount_exact IS NULL OR (amount_exact >= 0.01 AND amount_exact <= 999999999.99)",
            name="ck_planned_expenses_amount_exact_range",
        ),
        sa.CheckConstraint(
            "amount_min IS NULL OR (amount_min >= 0.01 AND amount_min <= 999999999.99)",
            name="ck_planned_expenses_amount_min_range",
        ),
        sa.CheckConstraint(
            "amount_max IS NULL OR (amount_max >= 0.01 AND amount_max <= 999999999.99)",
            name="ck_planned_expenses_amount_max_range",
        ),
    )

    # --- transactions ---
    op.create_table(
        "transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("type", sa.Enum("income", "expense", "transfer", "credit_card_payment", name="transactiontype", create_type=False), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("scope", sa.Enum("personal", "shared", name="transactionscope", create_type=False), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=True),
        sa.Column("destination_account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=True),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("categories.id"), nullable=True),
        sa.Column("recurring_rule_id", sa.Integer(), sa.ForeignKey("recurring_rules.id"), nullable=True),
        sa.Column("posted", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("statement_closing_date", sa.Date(), nullable=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("amount >= 0.01 AND amount <= 999999999.99", name="ck_transactions_amount_range"),
    )

    # --- transaction_splits ---
    op.create_table(
        "transaction_splits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("transaction_id", sa.Integer(), sa.ForeignKey("transactions.id"), nullable=False),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("categories.id"), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.CheckConstraint("amount > 0", name="ck_transaction_splits_amount_positive"),
    )

    # --- transaction_tags (association table) ---
    op.create_table(
        "transaction_tags",
        sa.Column("transaction_id", sa.Integer(), sa.ForeignKey("transactions.id"), primary_key=True),
        sa.Column("tag_id", sa.Integer(), sa.ForeignKey("tags.id"), primary_key=True),
    )

    # --- transaction_planned_expenses ---
    op.create_table(
        "transaction_planned_expenses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("transaction_id", sa.Integer(), sa.ForeignKey("transactions.id"), nullable=False),
        sa.Column("planned_expense_id", sa.Integer(), sa.ForeignKey("planned_expenses.id"), nullable=False),
        sa.Column("resolved_amount", sa.Numeric(12, 2), nullable=False),
    )

    # --- shared_expenses ---
    op.create_table(
        "shared_expenses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("transaction_id", sa.Integer(), sa.ForeignKey("transactions.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    # --- shared_expense_shares ---
    op.create_table(
        "shared_expense_shares",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("shared_expense_id", sa.Integer(), sa.ForeignKey("shared_expenses.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("settled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("settled_at", sa.DateTime(), nullable=True),
    )

    # --- settlements ---
    op.create_table(
        "settlements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("from_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("to_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("amount >= 0.01 AND amount <= 999999999.99", name="ck_settlements_amount_range"),
        sa.CheckConstraint("from_user_id != to_user_id", name="ck_settlements_different_users"),
    )

    # --- settlement_allocations ---
    op.create_table(
        "settlement_allocations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("settlement_id", sa.Integer(), sa.ForeignKey("settlements.id"), nullable=False),
        sa.Column("shared_expense_share_id", sa.Integer(), sa.ForeignKey("shared_expense_shares.id"), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
    )

    # --- budgets ---
    op.create_table(
        "budgets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("scope", sa.Enum("personal", "shared", name="budgetscope"), nullable=False),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("categories.id"), nullable=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("period", sa.Enum("weekly", "monthly", "quarterly", "yearly", name="budgetperiod"), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("amount >= 0.01 AND amount <= 999999999.99", name="ck_budgets_amount_range"),
    )

    # --- saving_goals ---
    op.create_table(
        "saving_goals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("target_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("scope", sa.Enum("personal", "shared", name="savinggoalscope"), nullable=False),
        sa.Column("status", sa.Enum("active", "completed", "cancelled", name="savinggoalstatus"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "target_amount IS NULL OR (target_amount >= 0.01 AND target_amount <= 999999999.99)",
            name="ck_saving_goals_target_amount_range",
        ),
    )

    # --- saving_contributions ---
    op.create_table(
        "saving_contributions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("saving_goal_id", sa.Integer(), sa.ForeignKey("saving_goals.id"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("amount >= 0.01 AND amount <= 999999999.99", name="ck_saving_contributions_amount_range"),
    )

    # --- credits ---
    op.create_table(
        "credits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("principal", sa.Numeric(12, 2), nullable=False),
        sa.Column("remaining_balance", sa.Numeric(12, 2), nullable=False),
        sa.Column("accrued_interest", sa.Numeric(12, 6), nullable=False, server_default="0.000000"),
        sa.Column("effective_yearly_rate", sa.Numeric(7, 6), nullable=False),
        sa.Column("disbursement_date", sa.Date(), nullable=False),
        sa.Column("interest_capitalization_day", sa.Integer(), nullable=False),
        sa.Column("status", sa.Enum("active", "paid_off", name="creditstatus"), nullable=False),
        sa.Column("scope", sa.Enum("personal", "shared", name="creditscope"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("converted_from_credit_card_payment", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("linked_transaction_id", sa.Integer(), sa.ForeignKey("transactions.id"), nullable=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("principal >= 0.01 AND principal <= 999999999.99", name="ck_credits_principal_range"),
        sa.CheckConstraint("effective_yearly_rate >= 0.0 AND effective_yearly_rate <= 1.0", name="ck_credits_rate_range"),
        sa.CheckConstraint("interest_capitalization_day >= 1 AND interest_capitalization_day <= 28", name="ck_credits_capitalization_day_range"),
    )

    # --- credit_payments ---
    op.create_table(
        "credit_payments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("credit_id", sa.Integer(), sa.ForeignKey("credits.id"), nullable=False),
        sa.Column("transaction_id", sa.Integer(), sa.ForeignKey("transactions.id"), nullable=False),
        sa.Column("total_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("interest_portion", sa.Numeric(12, 2), nullable=False),
        sa.Column("principal_portion", sa.Numeric(12, 2), nullable=False),
        sa.Column("manual_correction", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    # --- credit_forecast_cache ---
    op.create_table(
        "credit_forecast_cache",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("credit_id", sa.Integer(), sa.ForeignKey("credits.id"), nullable=False),
        sa.Column("month_offset", sa.Integer(), nullable=False),
        sa.Column("projected_balance", sa.Numeric(12, 2), nullable=False),
        sa.Column("projected_interest", sa.Numeric(12, 2), nullable=False),
        sa.Column("recalculated_at", sa.DateTime(), nullable=False),
    )

    # --- etf_positions ---
    op.create_table(
        "etf_positions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticker", sa.String(10), nullable=False),
        sa.Column("exchange_suffix", sa.String(10), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("shares", sa.Numeric(12, 6), nullable=False, server_default="0.000000"),
        sa.Column("average_buy_price", sa.Numeric(12, 6), nullable=False, server_default="0.000000"),
        sa.Column("current_price", sa.Numeric(12, 4), nullable=True),
        sa.Column("current_price_updated_at", sa.DateTime(), nullable=True),
        sa.Column("manual_price_override", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("consecutive_fetch_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("shares >= 0", name="ck_etf_positions_shares_non_negative"),
        sa.CheckConstraint("average_buy_price >= 0", name="ck_etf_positions_avg_price_non_negative"),
    )

    # --- etf_transactions ---
    op.create_table(
        "etf_transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("position_id", sa.Integer(), sa.ForeignKey("etf_positions.id"), nullable=False),
        sa.Column("type", sa.Enum("buy", "sell", name="etftransactiontype"), nullable=False),
        sa.Column("shares_quantity", sa.Numeric(12, 6), nullable=False),
        sa.Column("price_per_share", sa.Numeric(12, 6), nullable=False),
        sa.Column("total_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("linked_account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("shares_quantity > 0", name="ck_etf_transactions_shares_positive"),
        sa.CheckConstraint("price_per_share > 0", name="ck_etf_transactions_price_positive"),
    )

    # --- etf_price_history ---
    op.create_table(
        "etf_price_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("position_id", sa.Integer(), sa.ForeignKey("etf_positions.id"), nullable=False),
        sa.Column("price", sa.Numeric(12, 4), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.UniqueConstraint("position_id", "date", name="uq_etf_price_history_position_date"),
    )

    # --- etf_savings_plans ---
    op.create_table(
        "etf_savings_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("position_id", sa.Integer(), sa.ForeignKey("etf_positions.id"), nullable=False),
        sa.Column("recurring_rule_id", sa.Integer(), sa.ForeignKey("recurring_rules.id"), nullable=False),
        sa.Column("linked_account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    # --- bavs ---
    op.create_table(
        "bavs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("type", sa.Enum("direktversicherung", "pensionskasse", "pensionsfonds", "direktzusage", "unterstuetzungskasse", name="bavtype"), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("employee_contribution_monthly", sa.Numeric(10, 2), nullable=False),
        sa.Column("employer_contribution_monthly", sa.Numeric(10, 2), nullable=False, server_default="0.00"),
        sa.Column("total_contribution_monthly", sa.Numeric(10, 2), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "employee_contribution_monthly >= 0.01 AND employee_contribution_monthly <= 50000.00",
            name="ck_bavs_employee_contribution_range",
        ),
        sa.CheckConstraint(
            "employer_contribution_monthly >= 0.00 AND employer_contribution_monthly <= 50000.00",
            name="ck_bavs_employer_contribution_range",
        ),
    )

    # --- bav_contribution_logs ---
    op.create_table(
        "bav_contribution_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("bav_id", sa.Integer(), sa.ForeignKey("bavs.id"), nullable=False),
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("employee_amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("employer_amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("bav_id", "month", name="uq_bav_contribution_logs_bav_month"),
    )

    # --- vls ---
    op.create_table(
        "vls",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("employer_contribution_monthly", sa.Numeric(10, 2), nullable=False),
        sa.Column("employee_contribution_monthly", sa.Numeric(10, 2), nullable=False, server_default="0.00"),
        sa.Column("total_contribution_monthly", sa.Numeric(10, 2), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("lock_up_end_date", sa.Date(), nullable=False),
        sa.Column("etf_position_id", sa.Integer(), sa.ForeignKey("etf_positions.id"), nullable=True),
        sa.Column("linked_account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=True),
        sa.Column("sparzulage_rate", sa.Numeric(5, 4), nullable=False, server_default="0.20"),
        sa.Column("annual_eligible_max", sa.Numeric(10, 2), nullable=False, server_default="400.00"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    # --- vl_contribution_logs ---
    op.create_table(
        "vl_contribution_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("vl_id", sa.Integer(), sa.ForeignKey("vls.id"), nullable=False),
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("etf_transaction_id", sa.Integer(), sa.ForeignKey("etf_transactions.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("vl_id", "month", name="uq_vl_contribution_logs_vl_month"),
    )

    # --- notifications ---
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column("message", sa.String(500), nullable=False),
        sa.Column("read", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("link_url", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
    op.create_index("ix_notifications_type", "notifications", ["type"])

    # --- import_column_mappings ---
    op.create_table(
        "import_column_mappings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("bank_name", sa.String(100), nullable=True),
        sa.Column("date_column", sa.Integer(), nullable=False),
        sa.Column("amount_column", sa.Integer(), nullable=False),
        sa.Column("description_column", sa.Integer(), nullable=True),
        sa.Column("date_format", sa.String(20), nullable=False),
        sa.Column("delimiter", sa.String(1), nullable=False),
        sa.Column("decimal_separator", sa.String(1), nullable=False),
        sa.Column("encoding", sa.String(20), nullable=False, server_default="utf-8"),
        sa.UniqueConstraint("account_id", "bank_name", name="uq_import_column_mappings_account_bank"),
    )

    # --- import_logs ---
    op.create_table(
        "import_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("total_rows", sa.Integer(), nullable=False),
        sa.Column("imported_rows", sa.Integer(), nullable=False),
        sa.Column("skipped_rows", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    # --- net_worth_snapshots ---
    op.create_table(
        "net_worth_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("total_value", sa.Numeric(14, 2), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "snapshot_date", name="uq_net_worth_snapshots_user_date"),
    )

    # --- audit_logs ---
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("action", sa.Enum("create", "update", "delete", name="auditaction"), nullable=False),
        sa.Column("model", sa.String(50), nullable=False),
        sa.Column("record_id", sa.Integer(), nullable=False),
        sa.Column("old_values", sa.JSON(), nullable=True),
        sa.Column("new_values", sa.JSON(), nullable=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])
    op.create_index("ix_audit_logs_model_record", "audit_logs", ["model", "record_id"])
    op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"])


def downgrade() -> None:
    # Drop tables in reverse order to respect foreign key dependencies
    op.drop_index("ix_audit_logs_user_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_model_record", table_name="audit_logs")
    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_table("net_worth_snapshots")
    op.drop_table("import_logs")
    op.drop_table("import_column_mappings")
    op.drop_index("ix_notifications_type", table_name="notifications")
    op.drop_index("ix_notifications_user_id", table_name="notifications")
    op.drop_table("notifications")
    op.drop_table("vl_contribution_logs")
    op.drop_table("vls")
    op.drop_table("bav_contribution_logs")
    op.drop_table("bavs")
    op.drop_table("etf_savings_plans")
    op.drop_table("etf_price_history")
    op.drop_table("etf_transactions")
    op.drop_table("etf_positions")
    op.drop_table("credit_forecast_cache")
    op.drop_table("credit_payments")
    op.drop_table("credits")
    op.drop_table("saving_contributions")
    op.drop_table("saving_goals")
    op.drop_table("budgets")
    op.drop_table("settlement_allocations")
    op.drop_table("settlements")
    op.drop_table("shared_expense_shares")
    op.drop_table("shared_expenses")
    op.drop_table("transaction_planned_expenses")
    op.drop_table("transaction_tags")
    op.drop_table("transaction_splits")
    op.drop_table("transactions")
    op.drop_table("planned_expenses")
    op.drop_table("recurring_rule_splits")
    op.drop_table("recurring_rules")
    op.drop_table("tags")
    op.drop_table("categories")
    op.drop_table("account_balance_snapshots")
    op.drop_table("account_owners")
    op.drop_table("accounts")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")

    # Drop enum types
    sa.Enum(name="auditaction").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="etftransactiontype").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="bavtype").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="creditscope").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="creditstatus").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="savinggoalstatus").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="savinggoalscope").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="budgetperiod").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="budgetscope").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="plannedexpensescope").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="transactionscope").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="transactiontype").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="recurringfrequency").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="snapshotsource").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="accountscope").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="accounttype").drop(op.get_bind(), checkfirst=True)
