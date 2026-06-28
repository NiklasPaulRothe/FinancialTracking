"""Saving goal service for Haushaltsbuch.

Implements creating saving goals, adding/removing contributions,
completing/cancelling goals, and progress calculation.

Validates: Requirements 10.1, 10.2, 10.3, 10.4, 10.5, 10.6
"""

from decimal import Decimal

from app.extensions import db
from app.models.account import Account
from app.models.budget import (
    SavingGoal,
    SavingGoalScope,
    SavingGoalStatus,
    SavingContribution,
)
from app.models.user import User


class SavingGoalService:
    """Service class for saving goal business logic.

    Manages the lifecycle of saving goals including creation,
    contribution management, completion, and cancellation.
    """

    def create_saving_goal(
        self,
        user: User,
        name: str,
        scope: str | SavingGoalScope,
        target_amount: Decimal | None = None,
    ) -> SavingGoal:
        """Create a new saving goal with status active.

        Validates: Requirement 10.1

        Args:
            user: The owning user.
            name: Goal name (1-100 characters).
            scope: 'personal' or 'shared'.
            target_amount: Optional target amount (0.01-999999999.99).

        Returns:
            The newly created SavingGoal instance.

        Raises:
            ValueError: If name is empty or too long, or target_amount is invalid.
        """
        # Validate name
        if not name or len(name.strip()) == 0:
            raise ValueError("Saving goal name must not be empty.")
        if len(name) > 100:
            raise ValueError(
                "Saving goal name must be between 1 and 100 characters."
            )

        # Validate target_amount if provided
        if target_amount is not None:
            if target_amount < Decimal("0.01") or target_amount > Decimal("999999999.99"):
                raise ValueError(
                    "Target amount must be between 0.01 and 999,999,999.99."
                )

        # Resolve scope enum
        if isinstance(scope, str):
            try:
                scope = SavingGoalScope(scope)
            except ValueError:
                raise ValueError(
                    f"Invalid scope '{scope}'. Must be 'personal' or 'shared'."
                )

        goal = SavingGoal(
            name=name.strip(),
            target_amount=target_amount,
            scope=scope,
            status=SavingGoalStatus.active,
            user_id=user.id,
        )
        db.session.add(goal)
        db.session.commit()
        return goal

    def create(
        self,
        name: str,
        scope,
        user_id: int,
        target_amount: Decimal | None = None,
    ) -> SavingGoal:
        """Create a new saving goal (blueprint-compatible interface).

        Validates: Requirement 10.1

        Args:
            name: Goal name (1-100 characters).
            scope: SavingGoalScope or TransactionScope value.
            user_id: The owning user's ID.
            target_amount: Optional target amount.

        Returns:
            The newly created SavingGoal instance.
        """
        # Convert scope to SavingGoalScope if needed
        if hasattr(scope, 'value'):
            scope_value = scope.value
        else:
            scope_value = str(scope)

        try:
            saving_scope = SavingGoalScope(scope_value)
        except ValueError:
            raise ValueError(
                f"Invalid scope '{scope_value}'. Must be 'personal' or 'shared'."
            )

        goal = SavingGoal(
            name=name.strip() if name else "",
            target_amount=target_amount,
            scope=saving_scope,
            status=SavingGoalStatus.active,
            user_id=user_id,
        )
        db.session.add(goal)
        db.session.commit()
        return goal

    def add_contribution(
        self,
        goal_id: int | None = None,
        account_id: int | None = None,
        amount: Decimal | None = None,
        user: User | None = None,
        goal: SavingGoal | None = None,
    ) -> SavingContribution:
        """Add a contribution to a saving goal from an account.

        Validates: Requirement 10.2

        Supports two calling conventions:
        1. (goal_id, account_id, amount, user) - validates access
        2. (goal=goal, account_id=account_id, amount=amount) - direct

        Args:
            goal_id: The saving goal ID (option 1).
            account_id: The account to contribute from.
            amount: Contribution amount (0.01-999999999.99).
            user: The requesting user (option 1).
            goal: The saving goal instance (option 2).

        Returns:
            The newly created SavingContribution instance.

        Raises:
            ValueError: If goal not found, not active, account not found,
                user lacks access, or amount is invalid.
        """
        if goal is not None:
            # Blueprint-style call: goal object passed directly
            resolved_goal = goal
        elif goal_id is not None:
            resolved_goal = db.session.get(SavingGoal, goal_id)
            if resolved_goal is None:
                raise ValueError(f"Saving goal with id {goal_id} not found.")
        else:
            raise ValueError("Either goal_id or goal must be provided.")

        if resolved_goal.status != SavingGoalStatus.active:
            raise ValueError(
                "Cannot add contributions to a completed or cancelled goal."
            )

        # Validate user access if user is provided
        if user is not None and resolved_goal.user_id != user.id:
            raise ValueError("User does not have access to this saving goal.")

        # Validate account exists
        if account_id is None:
            raise ValueError("account_id must be provided.")
        account = db.session.get(Account, account_id)
        if account is None:
            raise ValueError(f"Account with id {account_id} not found.")

        # Validate user has access to the account (if user provided)
        if user is not None and account.owner_id != user.id:
            from app.models.account import AccountOwner

            is_co_owner = AccountOwner.query.filter_by(
                account_id=account.id, user_id=user.id
            ).first() is not None
            if not is_co_owner:
                raise ValueError(
                    "User does not have access to this account."
                )

        # Validate amount
        if amount is None:
            raise ValueError("Amount must be provided.")
        if amount < Decimal("0.01") or amount > Decimal("999999999.99"):
            raise ValueError(
                "Contribution amount must be between 0.01 and 999,999,999.99."
            )

        contribution = SavingContribution(
            saving_goal_id=resolved_goal.id,
            account_id=account.id,
            amount=amount,
        )
        db.session.add(contribution)
        db.session.commit()
        return contribution

    def remove_contribution(
        self,
        contribution_id: int | None = None,
        user: User | None = None,
        contribution: SavingContribution | None = None,
    ) -> None:
        """Remove a contribution from a saving goal.

        Validates: Requirement 10.6

        Supports two calling conventions:
        1. (contribution_id, user) - validates access
        2. (contribution=contribution) - direct

        Args:
            contribution_id: The contribution ID (option 1).
            user: The requesting user (option 1).
            contribution: The contribution instance (option 2).

        Raises:
            ValueError: If contribution not found or user lacks access.
        """
        if contribution is not None:
            resolved_contribution = contribution
        elif contribution_id is not None:
            resolved_contribution = db.session.get(SavingContribution, contribution_id)
            if resolved_contribution is None:
                raise ValueError(
                    f"Saving contribution with id {contribution_id} not found."
                )
        else:
            raise ValueError("Either contribution_id or contribution must be provided.")

        # Validate user access through the goal (if user provided)
        if user is not None:
            goal = resolved_contribution.saving_goal
            if goal.user_id != user.id:
                raise ValueError(
                    "User does not have access to this saving contribution."
                )
            if goal.status != SavingGoalStatus.active:
                raise ValueError(
                    "Cannot remove contributions from a completed or cancelled goal."
                )

        db.session.delete(resolved_contribution)
        db.session.commit()

    def complete_goal(self, goal_id: int, user: User) -> SavingGoal:
        """Mark a saving goal as completed, releasing contributions.

        Validates: Requirement 10.5

        Args:
            goal_id: The goal to complete.
            user: The requesting user.

        Returns:
            The updated SavingGoal instance.

        Raises:
            ValueError: If goal not found, not active, or user lacks access.
        """
        goal = self._get_active_goal(goal_id, user)
        goal.status = SavingGoalStatus.completed
        db.session.commit()
        return goal

    def complete(self, goal: SavingGoal) -> None:
        """Mark a saving goal as completed (blueprint-compatible).

        Validates: Requirement 10.5
        """
        goal.status = SavingGoalStatus.completed
        db.session.commit()

    def cancel_goal(self, goal_id: int, user: User) -> SavingGoal:
        """Cancel a saving goal, releasing contributions.

        Validates: Requirement 10.5

        Args:
            goal_id: The goal to cancel.
            user: The requesting user.

        Returns:
            The updated SavingGoal instance.

        Raises:
            ValueError: If goal not found, not active, or user lacks access.
        """
        goal = self._get_active_goal(goal_id, user)
        goal.status = SavingGoalStatus.cancelled
        db.session.commit()
        return goal

    def cancel(self, goal: SavingGoal) -> None:
        """Cancel a saving goal (blueprint-compatible).

        Validates: Requirement 10.5
        """
        goal.status = SavingGoalStatus.cancelled
        db.session.commit()

    def get_progress(self, goal: SavingGoal) -> Decimal | None:
        """Calculate saving goal progress as a percentage.

        Validates: Requirements 10.3, 10.4

        Progress = sum(contributions) / target_amount * 100

        Args:
            goal: The saving goal to calculate progress for.

        Returns:
            Progress percentage as Decimal, or None if no target_amount
            (open-ended goal per Req 10.4).
        """
        if goal.target_amount is None:
            return None

        total_contributions = self._get_contributions_total(goal)

        if goal.target_amount == Decimal("0"):
            return Decimal("0")

        progress = (total_contributions / goal.target_amount) * Decimal("100")
        return progress

    def get_contributions_total(self, goal: SavingGoal) -> Decimal:
        """Get the total sum of all contributions for a goal.

        Useful for open-ended goals (Req 10.4) to display the accumulated total.

        Args:
            goal: The saving goal.

        Returns:
            Sum of all contribution amounts.
        """
        return self._get_contributions_total(goal)

    def get_for_user(self, user_id: int) -> list[SavingGoal]:
        """Get all saving goals for a user ordered by status and name."""
        return (
            SavingGoal.query.filter_by(user_id=user_id)
            .order_by(SavingGoal.status.asc(), SavingGoal.name.asc())
            .all()
        )

    def get_by_id(self, goal_id: int) -> SavingGoal | None:
        """Get a saving goal by ID."""
        return db.session.get(SavingGoal, goal_id)

    def get_contribution_by_id(self, contribution_id: int) -> SavingContribution | None:
        """Get a contribution by ID."""
        return db.session.get(SavingContribution, contribution_id)

    # -------------------------------------------------------------------------
    # Private helpers
    # -------------------------------------------------------------------------

    def _get_active_goal(self, goal_id: int, user: User) -> SavingGoal:
        """Retrieve an active saving goal for the user.

        Args:
            goal_id: The goal ID.
            user: The requesting user.

        Returns:
            The SavingGoal instance.

        Raises:
            ValueError: If goal not found, not active, or user lacks access.
        """
        goal = db.session.get(SavingGoal, goal_id)
        if goal is None:
            raise ValueError(f"Saving goal with id {goal_id} not found.")
        if goal.user_id != user.id:
            raise ValueError("User does not have access to this saving goal.")
        if goal.status != SavingGoalStatus.active:
            raise ValueError(
                "Saving goal is not active. Only active goals can be modified."
            )
        return goal

    def _get_contributions_total(self, goal: SavingGoal) -> Decimal:
        """Sum all contribution amounts for a goal.

        Args:
            goal: The saving goal.

        Returns:
            Total contribution amount as Decimal.
        """
        from sqlalchemy import func

        total = (
            db.session.query(
                func.coalesce(func.sum(SavingContribution.amount), 0)
            )
            .filter(SavingContribution.saving_goal_id == goal.id)
            .scalar()
        )
        return Decimal(str(total))
