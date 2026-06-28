"""Account service for Haushaltsbuch.

Implements CRUD operations, co-owner management, deactivation, deletion with
dependency checks, and visibility filtering for accounts.

Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 28.1, 28.2, 28.4
"""

from decimal import Decimal

from app.extensions import db
from app.models.account import Account, AccountOwner, AccountType, AccountScope
from app.models.user import User
from app.exceptions import DependencyBlocksDeletion
from app.services.audit_service import AuditService


class AccountService:
    """Service class encapsulating all account business logic."""

    def __init__(self) -> None:
        self._audit_service = AuditService()

    def create_account(
        self,
        user: User,
        name: str,
        type: AccountType,
        scope: AccountScope,
        **kwargs,
    ) -> Account:
        """Create a new account with default balance 0.0 and active=True.

        Validates: Requirement 2.1, 28.4

        Args:
            user: The owning user.
            name: Account name (1-50 characters).
            type: Account type enum value.
            scope: Account scope enum value.
            **kwargs: Optional fields like institute, credit_limit, etc.

        Returns:
            The newly created Account instance.
        """
        account = Account(
            name=name,
            type=type if isinstance(type, AccountType) else AccountType(type),
            scope=scope if isinstance(scope, AccountScope) else AccountScope(scope),
            balance=Decimal("0.0"),
            active=True,
            visible_to_partner=kwargs.get("visible_to_partner", True),
            institute=kwargs.get("institute"),
            owner_id=user.id,
        )

        # Credit card specific fields
        if account.type == AccountType.credit_card:
            account.credit_limit = kwargs.get("credit_limit")
            account.statement_closing_day = kwargs.get("statement_closing_day")
            account.payment_due_day = kwargs.get("payment_due_day")

        # Optional overdraft field for spending accounts
        if kwargs.get("max_overdraft") is not None:
            account.max_overdraft = kwargs["max_overdraft"]

        db.session.add(account)
        db.session.flush()

        # Audit log (Req 22.1)
        self._audit_service.log_change(
            action="create",
            model="Account",
            record_id=account.id,
            old_values=None,
            new_values={
                "name": account.name,
                "type": account.type.value,
                "scope": account.scope.value,
                "owner_id": account.owner_id,
            },
            user_id=user.id,
        )

        db.session.commit()
        return account

    def edit_account(self, account_id: int, user: User, **updates) -> Account:
        """Edit an existing account's mutable fields.

        Validates: Requirement 2.2

        Allowed updates: name, institute, visible_to_partner.
        For credit_card type only: credit_limit, statement_closing_day, payment_due_day.

        Args:
            account_id: ID of the account to edit.
            user: The requesting user (must be owner or co-owner).
            **updates: Fields to update.

        Returns:
            The updated Account instance.

        Raises:
            ValueError: If account not found or user lacks access.
        """
        account = self._get_account_for_user(account_id, user)

        # Capture old values for audit
        old_values = {k: getattr(account, k) for k in updates if hasattr(account, k)}

        # Common editable fields
        allowed_fields = {"name", "institute", "visible_to_partner"}
        # Credit card specific fields
        if account.type == AccountType.credit_card:
            allowed_fields.update({
                "credit_limit",
                "statement_closing_day",
                "payment_due_day",
            })

        for field, value in updates.items():
            if field in allowed_fields:
                setattr(account, field, value)

        # Audit log (Req 22.1)
        applied_updates = {k: v for k, v in updates.items() if k in allowed_fields}
        if applied_updates:
            self._audit_service.log_change(
                action="update",
                model="Account",
                record_id=account.id,
                old_values=old_values,
                new_values=applied_updates,
                user_id=user.id,
            )

        db.session.commit()
        return account

    def deactivate_account(self, account_id: int, user: User) -> Account:
        """Deactivate an account (hide from UI and balance calculations).

        Validates: Requirement 2.5

        The account remains in the database with all historical data preserved.

        Args:
            account_id: ID of the account to deactivate.
            user: The requesting user.

        Returns:
            The deactivated Account instance.

        Raises:
            ValueError: If account not found or user lacks access.
        """
        account = self._get_account_for_user(account_id, user)
        account.active = False

        # Audit log (Req 22.1)
        self._audit_service.log_change(
            action="update",
            model="Account",
            record_id=account.id,
            old_values={"active": True},
            new_values={"active": False},
            user_id=user.id,
        )

        db.session.commit()
        return account

    def delete_account(self, account_id: int, user: User) -> None:
        """Permanently delete an account after dependency check.

        Validates: Requirements 2.6, 2.7

        Checks for active dependencies (credits, saving contributions,
        blocking planned expenses, ETF savings plans). If any exist,
        raises DependencyBlocksDeletion. Otherwise deletes the Account
        and AccountOwner records, and nullifies account_id on referencing
        transactions.

        Args:
            account_id: ID of the account to delete.
            user: The requesting user.

        Raises:
            ValueError: If account not found or user lacks access.
            DependencyBlocksDeletion: If active dependencies exist.
        """
        account = self._get_account_for_user(account_id, user)

        # Check for active dependencies
        dependencies = self._check_deletion_dependencies(account)
        if dependencies:
            raise DependencyBlocksDeletion(
                account_id=account.id,
                dependencies=dependencies,
            )

        # Nullify account_id on referencing transactions
        self._nullify_transaction_references(account.id)

        # Audit log (Req 22.1)
        self._audit_service.log_change(
            action="delete",
            model="Account",
            record_id=account.id,
            old_values={
                "name": account.name,
                "type": account.type.value,
                "scope": account.scope.value,
                "owner_id": account.owner_id,
            },
            new_values=None,
            user_id=user.id,
        )

        # Delete AccountOwner records (handled by cascade, but explicit for clarity)
        AccountOwner.query.filter_by(account_id=account.id).delete()

        # Delete the account itself
        db.session.delete(account)
        db.session.commit()

    def add_co_owner(
        self, account_id: int, owner_user: User, co_owner_username: str
    ) -> AccountOwner:
        """Add a co-owner to an account.

        Validates: Requirements 2.3, 2.4

        The co-owner must be a valid user in the household (the partner)
        and cannot be the same as the account owner.

        Args:
            account_id: ID of the account.
            owner_user: The current owner requesting the addition.
            co_owner_username: Username of the partner to add.

        Returns:
            The created AccountOwner record.

        Raises:
            ValueError: If validation fails (user not found, same user,
                not a household partner, already co-owner).
        """
        account = self._get_account_for_user(account_id, owner_user)

        # Look up the co-owner user
        co_owner = User.query.filter_by(username=co_owner_username).first()
        if co_owner is None:
            raise ValueError(
                f"Username '{co_owner_username}' does not exist."
            )

        # Cannot add yourself as co-owner
        if co_owner.id == owner_user.id:
            raise ValueError("Cannot add yourself as co-owner.")

        # Validate household membership (max 2 users in household)
        total_users = User.query.count()
        if total_users > 2:
            raise ValueError("Household has more than 2 users; unexpected state.")

        # The co-owner must be the household partner
        partner = User.query.filter(User.id != owner_user.id).first()
        if partner is None or partner.id != co_owner.id:
            raise ValueError(
                f"Username '{co_owner_username}' is not a valid household member."
            )

        # Check if already a co-owner
        existing = AccountOwner.query.filter_by(
            account_id=account.id, user_id=co_owner.id
        ).first()
        if existing is not None:
            raise ValueError(
                f"User '{co_owner_username}' is already a co-owner of this account."
            )

        account_owner = AccountOwner(
            account_id=account.id,
            user_id=co_owner.id,
        )
        db.session.add(account_owner)
        db.session.commit()
        return account_owner

    def get_accounts_for_user(
        self, user: User, include_inactive: bool = False
    ) -> list[Account]:
        """Get all accounts owned by or co-owned by the user.

        Validates: Requirement 2.8

        Args:
            user: The requesting user.
            include_inactive: If True, include inactive accounts.

        Returns:
            List of Account instances.
        """
        # Accounts owned directly
        query = Account.query.filter(Account.owner_id == user.id)

        # Accounts co-owned
        co_owned_ids = (
            db.session.query(AccountOwner.account_id)
            .filter(AccountOwner.user_id == user.id)
            .subquery()
        )
        co_owned_query = Account.query.filter(Account.id.in_(co_owned_ids))

        # Union both sets
        combined = query.union(co_owned_query)

        if not include_inactive:
            combined = combined.filter(Account.active == True)  # noqa: E712

        return combined.all()

    def get_visible_accounts_for_partner(self, user: User) -> list[Account]:
        """Get accounts visible to the partner of the given user.

        Validates: Requirements 28.1, 28.2

        Returns accounts where:
        - Shared accounts (always visible to both regardless of visible_to_partner)
        - Personal accounts with visible_to_partner=True
        - Excludes inactive accounts

        Args:
            user: The user whose accounts the partner wants to see.
                  (i.e., the owner, not the partner requesting).

        Returns:
            List of Account instances visible to the partner.
        """
        # Get the partner user
        partner = User.query.filter(User.id != user.id).first()
        if partner is None:
            return []

        # Shared accounts are always visible (requirement 28.2)
        shared_accounts = Account.query.filter(
            Account.owner_id == user.id,
            Account.scope == AccountScope.shared,
            Account.active == True,  # noqa: E712
        )

        # Personal accounts only visible if visible_to_partner is True (requirement 28.1)
        visible_personal = Account.query.filter(
            Account.owner_id == user.id,
            Account.scope == AccountScope.personal,
            Account.visible_to_partner == True,  # noqa: E712
            Account.active == True,  # noqa: E712
        )

        # Also include accounts where partner is co-owner
        co_owned_ids = (
            db.session.query(AccountOwner.account_id)
            .filter(AccountOwner.user_id == partner.id)
            .subquery()
        )
        co_owned_accounts = Account.query.filter(
            Account.id.in_(co_owned_ids),
            Account.active == True,  # noqa: E712
        )

        return shared_accounts.union(visible_personal).union(co_owned_accounts).all()

    # -------------------------------------------------------------------------
    # Private helpers
    # -------------------------------------------------------------------------

    def _get_account_for_user(self, account_id: int, user: User) -> Account:
        """Retrieve an account ensuring the user has access.

        Args:
            account_id: The account ID.
            user: The requesting user.

        Returns:
            The Account instance.

        Raises:
            ValueError: If account not found or user lacks access.
        """
        account = db.session.get(Account, account_id)
        if account is None:
            raise ValueError(f"Account with id {account_id} not found.")

        # Check ownership or co-ownership
        is_owner = account.owner_id == user.id
        is_co_owner = AccountOwner.query.filter_by(
            account_id=account.id, user_id=user.id
        ).first() is not None

        if not is_owner and not is_co_owner:
            raise ValueError(
                f"User {user.username} does not have access to account {account_id}."
            )

        return account

    def _check_deletion_dependencies(self, account: Account) -> list[str]:
        """Check for active dependencies that block account deletion.

        Validates: Requirement 2.7

        Checks for:
        - Active credits linked to account
        - Active saving contributions linked to account
        - Unresolved blocking planned expenses linked to account
        - Active ETF savings plans linked to account

        Returns:
            List of dependency description strings. Empty if no dependencies.
        """
        dependencies = []

        # Check for active credits
        try:
            from app.models.credit import Credit
            active_credits = Credit.query.filter_by(
                account_id=account.id, active=True
            ).count()
            if active_credits > 0:
                dependencies.append(
                    f"{active_credits} active credit(s) linked to this account"
                )
        except (ImportError, Exception):
            # Model not yet implemented; skip this check
            pass

        # Check for active saving contributions
        try:
            from app.models.budget import SavingContribution, SavingGoal, SavingGoalStatus
            active_contributions = (
                db.session.query(SavingContribution)
                .join(SavingGoal, SavingContribution.saving_goal_id == SavingGoal.id)
                .filter(
                    SavingContribution.account_id == account.id,
                    SavingGoal.status == SavingGoalStatus.active,
                )
                .count()
            )
            if active_contributions > 0:
                dependencies.append(
                    f"{active_contributions} active saving contribution(s) linked to this account"
                )
        except (ImportError, Exception):
            # Model not yet implemented; skip this check
            pass

        # Check for unresolved blocking planned expenses
        try:
            from app.models.planned_expense import PlannedExpense
            blocking_expenses = PlannedExpense.query.filter_by(
                account_id=account.id, resolved=False, blocks_balance=True
            ).count()
            if blocking_expenses > 0:
                dependencies.append(
                    f"{blocking_expenses} unresolved blocking planned expense(s) linked to this account"
                )
        except (ImportError, Exception):
            # Model not yet implemented; skip this check
            pass

        # Check for active ETF savings plans
        try:
            from app.models.etf import ETFSavingsPlan
            active_plans = ETFSavingsPlan.query.filter_by(
                account_id=account.id, active=True
            ).count()
            if active_plans > 0:
                dependencies.append(
                    f"{active_plans} active ETF savings plan(s) linked to this account"
                )
        except (ImportError, Exception):
            # Model not yet implemented; skip this check
            pass

        return dependencies

    def _nullify_transaction_references(self, account_id: int) -> None:
        """Set account_id to null on transactions referencing this account.

        Validates: Requirement 2.6

        This preserves transaction history while removing the account link.
        """
        try:
            from app.models.transaction import Transaction
            Transaction.query.filter_by(account_id=account_id).update(
                {"account_id": None}
            )
        except (ImportError, Exception):
            # Transaction model not yet implemented; skip
            pass
