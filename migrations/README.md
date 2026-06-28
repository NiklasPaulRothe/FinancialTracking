# Database Migrations

This directory contains [Alembic](https://alembic.sqlalchemy.org/) migrations
managed through [Flask-Migrate](https://flask-migrate.readthedocs.io/).

## Prerequisites

- A running PostgreSQL instance
- The `DATABASE_URL` environment variable set (or use the default from `app/config.py`)

## Quick Start

```bash
# Set the Flask app entry point
export FLASK_APP=app:create_app

# Generate the initial migration (first time only)
flask db migrate -m "initial schema"

# Apply migrations to the database
flask db upgrade

# Roll back one revision
flask db downgrade
```

## Common Commands

| Command | Description |
|---------|-------------|
| `flask db init` | Already done — this directory is the result |
| `flask db migrate -m "description"` | Auto-generate a new revision |
| `flask db upgrade` | Apply all pending migrations |
| `flask db downgrade` | Revert the last migration |
| `flask db current` | Show current revision |
| `flask db history` | Show migration history |
| `flask db heads` | Show latest revision(s) |

## Generating the Initial Migration

Since the project uses PostgreSQL and migrations cannot be auto-generated without
a live database connection, follow these steps when you first set up the database:

```bash
# 1. Create the database
createdb haushaltsbuch_dev

# 2. Set the connection URL (if not using the default)
export DATABASE_URL="postgresql://user:pass@localhost/haushaltsbuch_dev"

# 3. Generate the migration
flask db migrate -m "initial schema – all models"

# 4. Apply it
flask db upgrade
```

## Models Covered

The initial migration will create tables for all models defined in `app/models/`:

- **User** — user accounts and preferences
- **Account, AccountOwner, AccountBalanceSnapshot** — financial accounts
- **Category** — transaction categories (hierarchical)
- **Tag, transaction_tags** — transaction tagging
- **Transaction, TransactionSplit, TransactionPlannedExpense** — core transactions
- **SharedExpense, SharedExpenseShare** — split household expenses
- **Settlement, SettlementAllocation** — debt settlements
- **RecurringRule, RecurringRuleSplit** — scheduled recurring transactions
- **Budget** — monthly/yearly budgets
- **PlannedExpense** — planned future expenses
- **SavingGoal, SavingContribution** — savings targets
- **Credit, CreditPayment, CreditForecastCache** — loans and credits
- **ETFPosition, ETFTransaction, ETFPriceHistory, ETFSavingsPlan** — ETF investments
- **BaV, BaVContributionLog** — company pension (Betriebliche Altersvorsorge)
- **VL, VLContributionLog** — capital-forming benefits (Vermögenswirksame Leistungen)
- **Notification** — user notifications
- **ImportColumnMapping, ImportLog** — CSV import configuration
- **NetWorthSnapshot** — periodic net worth snapshots
- **AuditLog** — change audit trail

## Notes

- Never edit migration files after they have been applied to a shared database.
- If you need to fix a migration, create a new revision that corrects the issue.
- The `versions/` directory is initially empty. The first `flask db migrate` call
  will populate it with the auto-generated schema.
