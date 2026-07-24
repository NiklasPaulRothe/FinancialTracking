# Haushaltsbuch — Technical Documentation

This document is intended for developers working on the codebase. It covers architecture, conventions, data flow, and the reasoning behind key design decisions.

---

## Table of Contents

1. [Overview](#overview)
2. [Technology Stack](#technology-stack)
3. [Project Structure](#project-structure)
4. [Application Lifecycle](#application-lifecycle)
5. [Architecture & Layering](#architecture--layering)
6. [Data Models](#data-models)
7. [Service Layer](#service-layer)
8. [Blueprint Layer](#blueprint-layer)
9. [Scheduler & Background Jobs](#scheduler--background-jobs)
10. [Key Business Concepts](#key-business-concepts)
11. [Authentication & Authorization](#authentication--authorization)
12. [Configuration](#configuration)
13. [Database & Migrations](#database--migrations)
14. [Frontend & Templates](#frontend--templates)
15. [Error Handling](#error-handling)
16. [Testing](#testing)
17. [Common Pitfalls & Notes](#common-pitfalls--notes)

---

## Overview

Haushaltsbuch is a personal and shared household finance tracker. It supports exactly **two users per household** who independently manage personal finances while collaboratively tracking shared expenses, budgets, and investments.

The application is a server-rendered monolith — no SPA frontend, no REST API. All state lives in PostgreSQL.

### Feature surface

- Multi-account management (spending, saving, credit card)
- Transaction CRUD with atomic balance updates (row-level locking)
- Recurring rules with catch-up processing
- Budgets aligned to income cycles (not calendar months)
- Planned expenses that block available balance
- Saving goals with per-account contributions
- Credit/loan tracking with interest accrual and repayment allocation
- Shared expense settlement (FIFO allocation)
- ETF portfolio tracking with Yahoo Finance price refresh
- ETF savings plans (recurring automated buys)
- Betriebliche Altersvorsorge (bAV) and Vermögenswirksame Leistungen (VL)
- CSV bank statement import
- Net worth snapshots and projections
- In-app notifications with per-cycle deduplication
- Append-only audit log

---

## Technology Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| Web Framework | Flask | 3.1.x |
| ORM | SQLAlchemy | 2.0.x |
| Migrations | Flask-Migrate (Alembic) | 4.0.x |
| Auth | Flask-Login + Werkzeug | 0.6.x |
| Forms | Flask-WTF + WTForms | 1.2.x / 3.2.x |
| Scheduler | Flask-APScheduler (APScheduler 3.x) | 1.13.x |
| Database | PostgreSQL | 15+ |
| ETF Data | yfinance | 0.2.x |
| Holidays | holidays (country=DE) | 0.62 |
| UI | Bootstrap 5 + Jinja2 | 5.3.x |
| Testing | pytest, Hypothesis, factory_boy, freezegun | various |

All dependencies are pinned in `requirements.txt`.

---

## Project Structure

```
app/
├── __init__.py              # Flask app factory (create_app)
├── config.py                # Config classes (Dev, Test, Prod)
├── extensions.py            # Extension instances (db, migrate, login_manager, scheduler, csrf)
├── exceptions.py            # Custom exception hierarchy
├── models/                  # SQLAlchemy declarative models
│   ├── __init__.py          # Re-exports all models
│   ├── user.py
│   ├── account.py
│   ├── transaction.py       # Transaction, RecurringRule, SharedExpense, Settlement, Tags
│   ├── budget.py            # Budget, SavingGoal, SavingContribution
│   ├── planned_expense.py
│   ├── credit.py
│   ├── etf.py
│   ├── bav.py               # BaV and VL models
│   ├── notification.py
│   ├── csv_import.py
│   ├── networth.py
│   ├── portfolio.py
│   └── audit.py
├── services/                # Business logic (all DB mutations happen here)
│   ├── transaction_service.py
│   ├── account_service.py
│   ├── balance_service.py
│   ├── budget_service.py
│   ├── recurring_service.py
│   ├── credit_service.py
│   ├── settlement_service.py
│   ├── etf_service.py
│   ├── bav_service.py
│   ├── vl_service.py
│   ├── import_service.py
│   ├── networth_service.py
│   ├── notification_service.py
│   ├── audit_service.py
│   ├── saving_goal_service.py
│   ├── planned_expense_service.py
│   └── banking_day_service.py
├── blueprints/              # Route handlers (thin controllers)
│   ├── auth/
│   ├── dashboard/
│   ├── accounts/
│   ├── transactions/
│   ├── recurring/
│   ├── budgets/
│   ├── planned_expenses/
│   ├── saving_goals/
│   ├── credits/
│   ├── settlements/
│   ├── etf/
│   ├── bav/
│   ├── vl/
│   ├── imports/
│   ├── reports/
│   ├── categories/
│   ├── tags/
│   ├── notifications/
│   └── settings/
├── scheduler/               # Background job definitions
├── templates/               # Jinja2 templates
└── static/                  # CSS, JS
sql/                         # Raw SQL schema + migration scripts
tests/                       # pytest suite (unit, integration, property)
migrations/                  # Alembic auto-generated migrations
run.py                       # Dev entry point
```

---

## Application Lifecycle

### Startup

1. `run.py` calls `create_app("development")` (or reads `FLASK_ENV`)
2. `create_app` in `app/__init__.py`:
   - Loads config from `app/config.py`
   - Initializes extensions: `db`, `migrate`, `login_manager`, `csrf`
   - Starts `APScheduler` (unless testing) and registers jobs
   - Registers all 19 blueprints
   - Attaches context processors (notification count), Jinja filters (`format_date`, `format_currency`), and error handlers (404, 500)

### Request cycle

```
Browser → Flask route (Blueprint) → WTForms validation → Service method → SQLAlchemy → PostgreSQL
                                                       ← Return model   ← Commit     ←
         ← Render Jinja2 template ←
```

Blueprints do no business logic. They validate forms, call services, and render templates.

---

## Architecture & Layering

The codebase enforces a strict three-layer separation:

### 1. Blueprint Layer (Controllers)

- Receives HTTP requests
- Validates input via WTForms
- Calls service layer methods
- Renders templates or redirects
- **Never touches `db.session` directly** (except for simple queries in index routes)

### 2. Service Layer

- Contains all business logic
- Performs all database writes within transactions
- Raises domain exceptions (`OverdraftLimitExceeded`, `InsufficientShares`, etc.)
- Uses `SELECT ... FOR UPDATE` for financial correctness on balance mutations
- Calls `AuditService.log_change()` for every financial mutation

### 3. Model Layer

- Pure SQLAlchemy declarative definitions
- Defines schema, relationships, check constraints
- Contains simple computed properties (e.g., `SavingGoal.progress_percent`)
- **No side effects, no session manipulation**

### Why this matters

Financial applications demand strict transactional boundaries. By consolidating all writes in the service layer, we guarantee that operations like "debit account A, credit account B, create snapshot, log audit" either all succeed or all roll back together.

---

## Data Models

The full schema is in `sql/create_database.sql`. Here's how the major entities relate:

### Core financial flow

```
User → Account → Transaction → (balance update, snapshot)
                             → SharedExpense → SharedExpenseShare → SettlementAllocation
                             → TransactionSplit (for transfers)
                             → TransactionPlannedExpense (links to PlannedExpense)
```

### Recurring automation

```
RecurringRule → (scheduler fires) → Transaction (auto-generated)
             → RecurringRuleSplit → TransactionSplit (copied)
             → CreditRepaymentSchedule → CreditPayment
```

### Investment tracking

```
User → InvestmentPortfolio → ETFPosition → ETFTransaction
                                         → ETFPriceHistory
                                         → ETFSavingsPlan → RecurringRule
```

### Key enums

| Enum | Values |
|------|--------|
| `TransactionType` | income, expense, transfer, credit_card_payment |
| `TransactionScope` | personal, shared |
| `AccountType` | spending, saving, reserve, credit_card |
| `AccountScope` | personal, shared |
| `RecurringFrequency` | daily, weekly, monthly, quarterly, yearly |
| `BudgetPeriod` | weekly, monthly, quarterly, yearly |
| `CreditStatus` | active, paid_off |
| `SavingGoalStatus` | active, completed, cancelled |

### Personal vs. Shared

Almost every entity has a `scope` field (personal/shared). This controls:
- Which user(s) can view/edit the record
- Whether `SharedExpense` records are auto-created on transactions
- Which transactions are summed in budget utilisation
- Which accounts appear in partner views

The `visible_to_partner` flag on personal accounts adds an additional privacy layer.

---

## Service Layer

### TransactionService

The most complex service. Handles:
- **Create**: validate amount → create Transaction row → flush (get ID) → assign credit card statement date → apply balance impacts (with row lock) → create snapshots → maybe create SharedExpense → audit → commit
- **Update**: reverse old impacts → update fields → apply new impacts → snapshot → audit → commit
- **Delete**: reverse impacts → unlink planned expenses → reverse credit payments → audit → delete → commit

Balance impacts use `SELECT ... FOR UPDATE` via `_lock_account()` to prevent race conditions.

### BalanceService

Computes `available_balance` which accounts for:
- Current balance
- Minus recurring expenses due before next income day
- Minus accumulated reserves for non-monthly recurring expenses
- Minus unresolved blocking planned expenses
- Minus active saving contributions

For credit cards: `available = credit_limit + balance` (balance is negative = debt).

### RecurringService

Processes all due rules for a user. Key behaviors:
- Catches up ALL missed dates (no limit) — if the app was offline for 3 months, it generates 3 months of transactions
- Duplicate prevention: checks if a transaction already exists for that rule+date
- Overdraft skip: if a posting would exceed overdraft, it skips that one date and still advances
- Copy splits: for transfer rules, copies `RecurringRuleSplit` → `TransactionSplit`
- Auto-links credit repayments and saving goal contributions

### BankingDayService

German banking day logic. Uses the `holidays` library (country=DE) to determine nationwide public holidays. Adjusts income days that fall on weekends/holidays backward to the last banking day.

### CreditService

- Daily interest: `remaining_balance * effective_yearly_rate / 365`
- Capitalization: accrued interest → remaining_balance, reset to 0
- Repayment allocation: interest portion first, then principal portion
- Forecast cache: pre-computes monthly projected balances up to 360 months

### SettlementService

FIFO allocation of settlement payments against outstanding `SharedExpenseShare` records (oldest creation date first).

### NotificationService

Deduplicates notifications per type per triggering entity per income cycle. The income cycle boundary is computed via `BankingDayService`.

### AuditService

Append-only. Entries are only deleted by the weekly purge job (>6 months old). No update or manual delete via application logic.

---

## Blueprint Layer

Each blueprint follows a consistent pattern:

```python
# blueprints/foo/__init__.py
foo_bp = Blueprint("foo", __name__, url_prefix="/foo", template_folder="templates")

@foo_bp.route("/")
@login_required
def index():
    # Query + render

@foo_bp.route("/create", methods=["GET", "POST"])
@login_required
def create():
    form = FooForm()
    if form.validate_on_submit():
        try:
            service.create(...)
            flash("Success", "success")
            return redirect(url_for("foo.index"))
        except SomeDomainError as e:
            flash(str(e), "danger")
    return render_template("foo/create.html", form=form)
```

Forms are defined in `blueprints/foo/forms.py` using Flask-WTF.

### URL prefix mapping

| Blueprint | Prefix | Purpose |
|-----------|--------|---------|
| auth | `/auth` | Login, register, logout |
| dashboard | `/` | Home page (personal/shared toggle) |
| accounts | `/accounts` | Account CRUD |
| transactions | `/transactions` | Transaction CRUD |
| recurring | `/recurring` | Recurring rule management |
| budgets | `/budgets` | Budget CRUD + utilisation |
| planned_expenses | `/planned-expenses` | Future expense tracking |
| saving_goals | `/saving-goals` | Goal + contribution management |
| credits | `/credits` | Loan tracking + repayments |
| settlements | `/settlements` | Shared expense settlement |
| etf | `/etf` | ETF portfolio |
| bav | `/bav` | Employer pension |
| vl | `/vl` | VL contracts |
| imports | `/import` | CSV bank import |
| reports | `/reports` | Personal, shared, net worth, Sankey |
| categories | `/categories` | Category CRUD |
| tags | `/tags` | Tag CRUD |
| notifications | `/notifications` | Notification list + mark read |
| settings | `/settings` | User preferences |

---

## Scheduler & Background Jobs

APScheduler runs in-process with a PostgreSQL job store. Jobs are registered in `app/scheduler/`.

### Daily job sequence (with advisory lock)

1. Acquire `pg_advisory_lock` (1-second timeout)
2. Process recurring rules (all users)
3. Refresh ETF prices (via yfinance)
4. Compute net worth snapshots
5. Capitalize credit interest (for credits whose capitalization day == today)
6. Release lock

If the lock can't be acquired (another worker is running), the entire run is skipped at INFO level.

Each task is wrapped in try/except — a failure in one task doesn't block the next.

### Weekly job

- **Audit purge** (Sundays): deletes AuditLog entries older than 6 months

### Monthly jobs

- **bAV contribution logs**: generates monthly log rows for active contracts
- **VL contribution logs**: generates monthly log rows + ETF buys if position linked

---

## Key Business Concepts

### Income Cycle

The foundational time unit in this application. Unlike calendar months, the income cycle runs from one effective income day to the day before the next. All budget periods, available balance projections, and recurring expense deductions are aligned to this boundary.

The income day is set per user (1-31) and adjusted for German banking days.

### Available Balance

Not the same as account balance. Available balance = balance minus obligations:
- Recurring expenses due before next income day
- Accumulated reserves for non-monthly recurring expenses (e.g., yearly subscription: amount/12 reserved per month elapsed)
- Blocking planned expenses
- Active saving contributions

This answers "how much can I actually spend today?"

### Shared Expenses & Settlements

When a user creates a transaction with scope="shared" (income, expense, or credit_card_payment), the system auto-creates a `SharedExpense` with two `SharedExpenseShare` records (50/50 split).

Settlements are repayments between partners. They're allocated FIFO against outstanding shares. Full allocation sets `settled=True`.

### Credit Card Handling

- Balance is **negative** (represents debt owed)
- Available credit = `credit_limit + balance`
- Transactions are assigned a `statement_closing_date` based on the account's `statement_closing_day`
- Pending transactions (`posted=False`) reduce available credit but don't appear in statement balances
- Can be converted to mini-credits for installment tracking

---

## Authentication & Authorization

- Flask-Login manages sessions
- Passwords are hashed with Werkzeug (`generate_password_hash` / `check_password_hash`)
- Max 2 users per household (enforced at registration)
- All routes except `/auth/login` and `/auth/register` require `@login_required`
- Data isolation: services always filter by `user_id` or check ownership
- Shared records are accessible by both household members
- `visible_to_partner` on personal accounts adds optional privacy

### Template behavior

`base.html` uses `{% if current_user.is_authenticated %}` to switch between:
- **Authenticated**: full sidebar layout with navigation
- **Unauthenticated**: centered card layout (used by login/register via `{% block content_unauth %}`)

---

## Configuration

Three config classes in `app/config.py`:

| Config | Use |
|--------|-----|
| `DevelopmentConfig` | Local dev. Debug=True, local PostgreSQL. |
| `TestingConfig` | Test suite. CSRF disabled, separate DB (`haushaltsbuch_test`), in-memory job store. |
| `ProductionConfig` | Production. Secure cookies, HTTPS scheme. |

Environment variables (loaded from `.env`):
- `DATABASE_URL` — PostgreSQL connection string
- `SECRET_KEY` — Flask session signing key
- `TEST_DATABASE_URL` — Test database (optional)

---

## Database & Migrations

### Schema creation (fresh install)

```bash
psql -U postgres -d haushaltsbuch -f sql/create_database.sql
```

This creates all tables, enums, constraints, indexes, and the APScheduler job table.

### Incremental migrations

Additional migrations are in `sql/001_*.sql` through `sql/009_*.sql`. Apply them in order for existing databases.

Flask-Migrate (Alembic) is also configured for ORM-driven migrations (`migrations/` directory).

### Key database features used

- **Enums**: PostgreSQL native enums for type safety
- **Check constraints**: Amount ranges, day ranges, referential integrity
- **Advisory locks**: `pg_advisory_lock` for scheduler concurrency
- **JSONB**: Audit log `old_values`/`new_values` columns
- **SELECT FOR UPDATE**: Row-level locking on accounts during balance mutations

---

## Frontend & Templates

- **Base template**: `app/templates/base.html` — dark-themed Bootstrap 5 layout with sidebar navigation
- **Pattern**: Each blueprint has its own `templates/` subfolder
- **CSS**: Custom dark theme in `static/css/theme.css`
- **JS**: Minimal — Bootstrap bundle + Chart.js for reports
- **Icons**: Bootstrap Icons
- **Font**: Inter (Google Fonts)

### Jinja filters (defined in app factory)

| Filter | Example | Output |
|--------|---------|--------|
| `format_date` | `{{ txn.date\|format_date }}` | `03.07.2026` (per user preference) |
| `format_currency` | `{{ amount\|format_currency }}` | `1.234,56 €` (German locale always) |
| `format_number` | `{{ value\|format_number }}` | `1.234,56` (no symbol) |

### Context processors

- `unread_notification_count`: injected globally for the nav badge
- `now()`: UTC timestamp for footer year

---

## Error Handling

### Exception hierarchy

```
HaushaltsbuchError (base)
├── OverdraftLimitExceeded     → Transaction would exceed overdraft
├── InsufficientShares         → ETF sell > available shares
├── DependencyBlocksDeletion   → Account has active credits/contributions/plans
├── HouseholdFullError         → 3rd user registration attempt
├── StalePriceError            → ETF price >3 days old
├── InvalidSettlementError     → from_user == to_user
└── SplitSumMismatchError      → Split amounts ≠ transaction total
```

### How errors surface

1. **WTForms validation** → inline field errors, page re-rendered
2. **Service exceptions** → caught in blueprint, shown as flash message
3. **Database constraint violations** → caught, translated to user-friendly message
4. **Scheduler task failures** → logged, skipped, next task continues
5. **External API failures** (yfinance) → logged, counter incremented, notification after 3 consecutive failures

---

## Testing

### Framework

- `pytest` as test runner
- `Hypothesis` for property-based tests (50 correctness properties defined in the design doc)
- `factory_boy` for model factories
- `freezegun` for date/time mocking
- `pytest-cov` for coverage

### Running tests

```bash
pytest                         # All tests
pytest tests/unit/             # Unit tests only
pytest tests/property/         # Property-based tests
pytest -k "test_transaction"   # Pattern matching
```

### Test database

Tests use `haushaltsbuch_test` (configurable via `TEST_DATABASE_URL`). CSRF is disabled in test config.

---

## Common Pitfalls & Notes

### Template blocks

`base.html` has TWO content blocks:
- `{% block content %}` — rendered only for authenticated users
- `{% block content_unauth %}` — rendered only for unauthenticated users

Login and register templates MUST use `content_unauth`.

### Balance mutations

Never update `account.balance` directly in a blueprint. Always go through `TransactionService` which:
1. Locks the account row
2. Checks overdraft limits
3. Creates balance snapshots
4. Writes audit entries

### SharedExpense creation

When creating shared transactions, the `SharedExpense` model requires `paid_by_user_id` and `total_amount` (NOT NULL). The `SharedExpenseShare` model requires `share_percentage` (NOT NULL). Always populate these fields.

### Recurring rule processing

The scheduler processes ALL missed dates without limit. If the app was down for 6 months, it will generate 6 months of transactions on the next run. This is intentional (Requirement 5.8).

### Decimal precision

- Monetary amounts: `Numeric(12, 2)`
- Interest accrual: `Numeric(12, 6)`
- Share quantities: `Numeric(12, 6)`
- Prices: `Numeric(12, 4)` or `Numeric(12, 6)`
- Percentages/rates: `Numeric(5, 4)` or `Numeric(7, 6)`

Always use `Decimal` in Python — never `float` for financial values.

### Scope filtering

When querying data, always consider the scope:
- Personal data: filter by `user_id == current_user.id`
- Shared data: may include both users
- Partner visibility: check `visible_to_partner` for personal accounts

### APScheduler and multiple workers

The advisory lock pattern means only ONE process executes scheduled jobs at a time. If you run multiple Gunicorn workers, only the first to acquire the lock runs the daily job. Others skip cleanly.

### German locale

All currency formatting uses German locale (comma as decimal separator, period as thousands separator). The `format_currency` Jinja filter handles this. Date format is user-configurable (DD.MM.YYYY, YYYY-MM-DD, or MM/DD/YYYY).
