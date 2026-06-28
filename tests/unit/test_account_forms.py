"""Unit tests for account blueprint forms.

Validates: Requirements 2.1, 2.2, 2.9
"""

import pytest
from app.blueprints.accounts.forms import AccountCreateForm, AccountEditForm
from app.models.account import AccountType, AccountScope


class TestAccountCreateForm:
    """Tests for AccountCreateForm validation."""

    def test_valid_spending_account(self, app):
        """A valid spending account form passes validation."""
        with app.test_request_context():
            form = AccountCreateForm(
                data={
                    "name": "Girokonto Haupt",
                    "type": AccountType.spending.value,
                    "scope": AccountScope.personal.value,
                    "visible_to_partner": True,
                }
            )
            assert form.validate(), form.errors

    def test_valid_credit_card_account(self, app):
        """A valid credit card form with all required CC fields passes."""
        with app.test_request_context():
            form = AccountCreateForm(
                data={
                    "name": "Visa Karte",
                    "type": AccountType.credit_card.value,
                    "scope": AccountScope.shared.value,
                    "visible_to_partner": True,
                    "credit_limit": "5000.00",
                    "statement_closing_day": "15",
                    "payment_due_day": "28",
                }
            )
            assert form.validate(), form.errors

    def test_name_required(self, app):
        """Name is required."""
        with app.test_request_context():
            form = AccountCreateForm(
                data={
                    "name": "",
                    "type": AccountType.spending.value,
                    "scope": AccountScope.personal.value,
                }
            )
            assert not form.validate()
            assert "name" in form.errors

    def test_name_max_length(self, app):
        """Name must be 50 characters or less."""
        with app.test_request_context():
            form = AccountCreateForm(
                data={
                    "name": "x" * 51,
                    "type": AccountType.spending.value,
                    "scope": AccountScope.personal.value,
                }
            )
            assert not form.validate()
            assert "name" in form.errors

    def test_credit_card_requires_credit_limit(self, app):
        """Credit card type requires credit_limit."""
        with app.test_request_context():
            form = AccountCreateForm(
                data={
                    "name": "Visa",
                    "type": AccountType.credit_card.value,
                    "scope": AccountScope.personal.value,
                    "statement_closing_day": "15",
                    "payment_due_day": "28",
                }
            )
            assert not form.validate()
            assert "credit_limit" in form.errors

    def test_credit_card_requires_statement_closing_day(self, app):
        """Credit card type requires statement_closing_day."""
        with app.test_request_context():
            form = AccountCreateForm(
                data={
                    "name": "Visa",
                    "type": AccountType.credit_card.value,
                    "scope": AccountScope.personal.value,
                    "credit_limit": "5000.00",
                    "payment_due_day": "28",
                }
            )
            assert not form.validate()
            assert "statement_closing_day" in form.errors

    def test_credit_card_requires_payment_due_day(self, app):
        """Credit card type requires payment_due_day."""
        with app.test_request_context():
            form = AccountCreateForm(
                data={
                    "name": "Visa",
                    "type": AccountType.credit_card.value,
                    "scope": AccountScope.personal.value,
                    "credit_limit": "5000.00",
                    "statement_closing_day": "15",
                }
            )
            assert not form.validate()
            assert "payment_due_day" in form.errors

    def test_credit_limit_min_value(self, app):
        """Credit limit must be at least 0.01."""
        with app.test_request_context():
            form = AccountCreateForm(
                data={
                    "name": "Visa",
                    "type": AccountType.credit_card.value,
                    "scope": AccountScope.personal.value,
                    "credit_limit": "0.00",
                    "statement_closing_day": "15",
                    "payment_due_day": "28",
                }
            )
            assert not form.validate()
            assert "credit_limit" in form.errors

    def test_statement_closing_day_range(self, app):
        """Statement closing day must be between 1 and 28."""
        with app.test_request_context():
            form = AccountCreateForm(
                data={
                    "name": "Visa",
                    "type": AccountType.credit_card.value,
                    "scope": AccountScope.personal.value,
                    "credit_limit": "5000.00",
                    "statement_closing_day": "29",
                    "payment_due_day": "15",
                }
            )
            assert not form.validate()
            assert "statement_closing_day" in form.errors

    def test_payment_due_day_range(self, app):
        """Payment due day must be between 1 and 28."""
        with app.test_request_context():
            form = AccountCreateForm(
                data={
                    "name": "Visa",
                    "type": AccountType.credit_card.value,
                    "scope": AccountScope.personal.value,
                    "credit_limit": "5000.00",
                    "statement_closing_day": "15",
                    "payment_due_day": "0",
                }
            )
            assert not form.validate()
            assert "payment_due_day" in form.errors

    def test_spending_account_ignores_cc_fields(self, app):
        """Spending account doesn't require credit card fields."""
        with app.test_request_context():
            form = AccountCreateForm(
                data={
                    "name": "Girokonto",
                    "type": AccountType.spending.value,
                    "scope": AccountScope.personal.value,
                }
            )
            assert form.validate(), form.errors


class TestAccountEditForm:
    """Tests for AccountEditForm validation."""

    def test_valid_edit_form(self, app):
        """A valid edit form passes validation."""
        with app.test_request_context():
            form = AccountEditForm(
                data={
                    "name": "Neuer Name",
                    "institute": "Sparkasse",
                    "visible_to_partner": True,
                }
            )
            assert form.validate(), form.errors

    def test_name_required(self, app):
        """Name is required for edit."""
        with app.test_request_context():
            form = AccountEditForm(
                data={
                    "name": "",
                    "visible_to_partner": True,
                }
            )
            assert not form.validate()
            assert "name" in form.errors

    def test_valid_credit_card_edit(self, app):
        """Credit card edit form with valid CC fields passes."""
        with app.test_request_context():
            form = AccountEditForm(
                data={
                    "name": "Visa",
                    "visible_to_partner": True,
                    "credit_limit": "10000.00",
                    "statement_closing_day": "20",
                    "payment_due_day": "5",
                }
            )
            assert form.validate(), form.errors

    def test_institute_max_length(self, app):
        """Institute field has max 100 chars."""
        with app.test_request_context():
            form = AccountEditForm(
                data={
                    "name": "Konto",
                    "institute": "x" * 101,
                    "visible_to_partner": True,
                }
            )
            assert not form.validate()
            assert "institute" in form.errors
