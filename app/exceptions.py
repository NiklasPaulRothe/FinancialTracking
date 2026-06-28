"""Custom exception hierarchy for Haushaltsbuch.

All application-specific exceptions inherit from HaushaltsbuchError,
enabling unified error handling in blueprints and services.
"""

from decimal import Decimal


class HaushaltsbuchError(Exception):
    """Base exception for all Haushaltsbuch application errors."""

    pass


class OverdraftLimitExceeded(HaushaltsbuchError):
    """Raised when a transaction would cause the account balance to drop
    below the negative max_overdraft limit.

    Validates: Requirement 3.9
    """

    def __init__(
        self,
        account_id: int,
        current_balance: Decimal,
        transaction_amount: Decimal,
        max_overdraft: Decimal,
    ) -> None:
        self.account_id = account_id
        self.current_balance = current_balance
        self.transaction_amount = transaction_amount
        self.max_overdraft = max_overdraft
        resulting_balance = current_balance - transaction_amount
        super().__init__(
            f"Transaction of {transaction_amount} on account {account_id} "
            f"would result in balance {resulting_balance}, "
            f"exceeding overdraft limit of -{max_overdraft}."
        )


class InsufficientShares(HaushaltsbuchError):
    """Raised when attempting to sell more ETF shares than currently held.

    Validates: Requirement 13.7
    """

    def __init__(
        self,
        position_id: int,
        available_shares: Decimal,
        requested_shares: Decimal,
    ) -> None:
        self.position_id = position_id
        self.available_shares = available_shares
        self.requested_shares = requested_shares
        super().__init__(
            f"Cannot sell {requested_shares} shares for position {position_id}; "
            f"only {available_shares} shares available."
        )


class DependencyBlocksDeletion(HaushaltsbuchError):
    """Raised when an account has active dependencies preventing deletion.

    Validates: Requirement 2.7
    """

    def __init__(self, account_id: int, dependencies: list[str]) -> None:
        self.account_id = account_id
        self.dependencies = dependencies
        deps_str = ", ".join(dependencies)
        super().__init__(
            f"Cannot delete account {account_id}; "
            f"active dependencies: {deps_str}."
        )


class HouseholdFullError(HaushaltsbuchError):
    """Raised when a registration is attempted but the household already
    has the maximum of 2 users.

    Validates: Requirement 1.8
    """

    def __init__(self) -> None:
        super().__init__(
            "Household is full. A maximum of 2 users are allowed."
        )


class StalePriceError(HaushaltsbuchError):
    """Raised when an ETF position's current price has not been updated
    for more than 3 days, blocking savings plan execution.

    Validates: Requirement 14.3
    """

    def __init__(self, position_id: int, days_stale: int) -> None:
        self.position_id = position_id
        self.days_stale = days_stale
        super().__init__(
            f"ETF position {position_id} price is {days_stale} days stale "
            f"(threshold: 3 days). Savings plan execution paused."
        )


class InvalidSettlementError(HaushaltsbuchError):
    """Raised when from_user equals to_user in a settlement.

    Validates: Requirement 12.7
    """

    def __init__(self, user_id: int) -> None:
        self.user_id = user_id
        super().__init__(
            f"Invalid settlement: from_user and to_user cannot be the same "
            f"(user_id={user_id})."
        )


class SplitSumMismatchError(HaushaltsbuchError):
    """Raised when the sum of transaction split amounts does not equal
    the transaction total amount.

    Validates: Requirement 4.4
    """

    def __init__(
        self,
        transaction_amount: Decimal,
        split_sum: Decimal,
    ) -> None:
        self.transaction_amount = transaction_amount
        self.split_sum = split_sum
        self.difference = transaction_amount - split_sum
        super().__init__(
            f"Split sum {split_sum} does not equal transaction amount "
            f"{transaction_amount} (difference: {self.difference})."
        )
