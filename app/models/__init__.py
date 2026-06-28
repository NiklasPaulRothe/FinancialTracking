"""SQLAlchemy models for Haushaltsbuch.

This package contains all declarative model classes. Import the db instance
from app.extensions and use it as the base for all models.

Usage:
    from app.models import db
    from app.models.user import User
    from app.models.account import Account
"""

from app.extensions import db
from app.models.user import User  # noqa: F401
from app.models.account import (  # noqa: F401
    Account,
    AccountOwner,
    AccountBalanceSnapshot,
    AccountType,
    AccountScope,
    SnapshotSource,
)
from app.models.category import Category  # noqa: F401
from app.models.budget import (  # noqa: F401
    Budget,
    BudgetScope,
    BudgetPeriod,
    SavingGoal,
    SavingContribution,
    SavingGoalScope,
    SavingGoalStatus,
)
from app.models.transaction import (  # noqa: F401
    Tag,
    Transaction,
    TransactionSplit,
    TransactionPlannedExpense,
    SharedExpense,
    SharedExpenseShare,
    Settlement,
    SettlementAllocation,
    RecurringRule,
    RecurringRuleSplit,
    TransactionType,
    TransactionScope,
    RecurringFrequency,
    transaction_tags,
)
from app.models.planned_expense import (  # noqa: F401
    PlannedExpense,
    PlannedExpenseScope,
)
from app.models.credit import (  # noqa: F401
    Credit,
    CreditPayment,
    CreditForecastCache,
    CreditRepaymentSchedule,
    CreditStatus,
    CreditScope,
)
from app.models.etf import (  # noqa: F401
    ETFPosition,
    ETFTransaction,
    ETFPriceHistory,
    ETFSavingsPlan,
    ETFTransactionType,
)
from app.models.bav import (  # noqa: F401
    BaV,
    BaVContributionLog,
    BaVType,
    VL,
    VLContributionLog,
)
from app.models.notification import Notification, NotificationPreference  # noqa: F401
from app.models.csv_import import (  # noqa: F401
    ImportColumnMapping,
    ImportLog,
)
from app.models.networth import NetWorthSnapshot  # noqa: F401
from app.models.portfolio import (  # noqa: F401
    InvestmentPortfolio,
    InvestmentPortfolioOwner,
)
from app.models.audit import (  # noqa: F401
    AuditLog,
    AuditAction,
)

__all__ = [
    "db",
    "User",
    "Account",
    "AccountOwner",
    "AccountBalanceSnapshot",
    "AccountType",
    "AccountScope",
    "SnapshotSource",
    "Category",
    "Budget",
    "BudgetScope",
    "BudgetPeriod",
    "SavingGoal",
    "SavingContribution",
    "SavingGoalScope",
    "SavingGoalStatus",
    "Tag",
    "Transaction",
    "TransactionSplit",
    "TransactionPlannedExpense",
    "SharedExpense",
    "SharedExpenseShare",
    "Settlement",
    "SettlementAllocation",
    "RecurringRule",
    "RecurringRuleSplit",
    "TransactionType",
    "TransactionScope",
    "RecurringFrequency",
    "transaction_tags",
    "PlannedExpense",
    "PlannedExpenseScope",
    "Credit",
    "CreditPayment",
    "CreditForecastCache",
    "CreditRepaymentSchedule",
    "CreditStatus",
    "CreditScope",
    "ETFPosition",
    "ETFTransaction",
    "ETFPriceHistory",
    "ETFSavingsPlan",
    "ETFTransactionType",
    "BaV",
    "BaVContributionLog",
    "BaVType",
    "VL",
    "VLContributionLog",
    "ImportColumnMapping",
    "ImportLog",
    "Notification",
    "NotificationPreference",
    "NetWorthSnapshot",
    "InvestmentPortfolio",
    "InvestmentPortfolioOwner",
    "AuditLog",
    "AuditAction",
]
