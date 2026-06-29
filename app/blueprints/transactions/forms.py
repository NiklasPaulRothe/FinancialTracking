"""WTForms form classes for the transactions blueprint.

Validates: Requirements 3.1, 3.5, 4.1
"""

from datetime import date
from decimal import Decimal

from wtforms import (
    DateField,
    DecimalField,
    SelectField,
    StringField,
    SubmitField,
)
from wtforms.validators import (
    DataRequired,
    Length,
    NumberRange,
    Optional,
)
from flask_wtf import FlaskForm

from app.models.transaction import TransactionScope, TransactionType


class TransactionCreateForm(FlaskForm):
    """Form for creating a new transaction.

    Validates: Requirement 3.1
    """

    type = SelectField(
        "Typ",
        choices=[
            (TransactionType.income.value, "Einnahme"),
            (TransactionType.expense.value, "Ausgabe"),
            (TransactionType.transfer.value, "Umbuchung"),
            (TransactionType.credit_card_payment.value, "Kreditkartenzahlung"),
        ],
        validators=[DataRequired(message="Typ ist erforderlich.")],
    )
    amount = DecimalField(
        "Betrag",
        validators=[
            DataRequired(message="Betrag ist erforderlich."),
            NumberRange(
                min=Decimal("0.01"),
                max=Decimal("999999999.99"),
                message="Betrag muss zwischen 0,01 und 999.999.999,99 liegen.",
            ),
        ],
        places=2,
    )
    date = DateField(
        "Datum",
        validators=[DataRequired(message="Datum ist erforderlich.")],
        default=date.today,
    )
    account_id = SelectField(
        "Konto",
        coerce=int,
        validators=[DataRequired(message="Konto ist erforderlich.")],
    )
    destination_account_id = SelectField(
        "Zielkonto",
        coerce=int,
        validators=[Optional()],
    )
    scope = SelectField(
        "Zuordnung",
        choices=[
            (TransactionScope.personal.value, "Persönlich"),
            (TransactionScope.shared.value, "Gemeinsam"),
        ],
        validators=[DataRequired(message="Zuordnung ist erforderlich.")],
    )
    category_id = SelectField(
        "Kategorie",
        coerce=int,
        validators=[Optional()],
    )
    description = StringField(
        "Beschreibung",
        validators=[
            Length(
                max=255,
                message="Beschreibung darf maximal 255 Zeichen lang sein.",
            ),
        ],
    )
    tags = StringField(
        "Tags (kommagetrennt)",
        validators=[
            Length(max=255),
        ],
    )
    submit = SubmitField("Transaktion erstellen")

    def __init__(self, *args, accounts=None, categories=None, **kwargs):
        """Initialize form with dynamic account and category choices.

        Args:
            accounts: List of Account objects for dropdowns.
            categories: List of Category objects for dropdown.
        """
        super().__init__(*args, **kwargs)

        account_choices = [(0, "— Konto wählen —")]
        if accounts:
            account_choices += [(a.id, a.name) for a in accounts]
        self.account_id.choices = account_choices
        self.destination_account_id.choices = [(0, "— Kein Zielkonto —")] + (
            [(a.id, a.name) for a in accounts] if accounts else []
        )

        category_choices = [(0, "— Keine Kategorie —")]
        if categories:
            category_choices += [(c.id, c.name) for c in categories]
        self.category_id.choices = category_choices

    def validate(self, extra_validators=None):
        """Custom validation for destination_account requirement."""
        rv = super().validate(extra_validators=extra_validators)

        # destination_account_id is required for transfer and credit_card_payment
        if self.type.data in (
            TransactionType.transfer.value,
            TransactionType.credit_card_payment.value,
        ):
            if not self.destination_account_id.data or self.destination_account_id.data == 0:
                self.destination_account_id.errors.append(
                    "Zielkonto ist für Umbuchungen und Kreditkartenzahlungen erforderlich."
                )
                rv = False

        # account_id must be selected (not the placeholder)
        if not self.account_id.data or self.account_id.data == 0:
            self.account_id.errors.append("Konto ist erforderlich.")
            rv = False

        # Coerce 0 to None for optional fields
        if self.destination_account_id.data == 0:
            self.destination_account_id.data = None
        if self.category_id.data == 0:
            self.category_id.data = None

        return rv


class TransactionEditForm(FlaskForm):
    """Form for editing an existing transaction.

    Validates: Requirement 3.11
    """

    type = SelectField(
        "Typ",
        choices=[
            (TransactionType.income.value, "Einnahme"),
            (TransactionType.expense.value, "Ausgabe"),
            (TransactionType.transfer.value, "Umbuchung"),
            (TransactionType.credit_card_payment.value, "Kreditkartenzahlung"),
        ],
        validators=[DataRequired(message="Typ ist erforderlich.")],
    )
    amount = DecimalField(
        "Betrag",
        validators=[
            DataRequired(message="Betrag ist erforderlich."),
            NumberRange(
                min=Decimal("0.01"),
                max=Decimal("999999999.99"),
                message="Betrag muss zwischen 0,01 und 999.999.999,99 liegen.",
            ),
        ],
        places=2,
    )
    date = DateField(
        "Datum",
        validators=[DataRequired(message="Datum ist erforderlich.")],
    )
    account_id = SelectField(
        "Konto",
        coerce=int,
        validators=[DataRequired(message="Konto ist erforderlich.")],
    )
    destination_account_id = SelectField(
        "Zielkonto",
        coerce=int,
        validators=[Optional()],
    )
    scope = SelectField(
        "Zuordnung",
        choices=[
            (TransactionScope.personal.value, "Persönlich"),
            (TransactionScope.shared.value, "Gemeinsam"),
        ],
        validators=[DataRequired(message="Zuordnung ist erforderlich.")],
    )
    category_id = SelectField(
        "Kategorie",
        coerce=int,
        validators=[Optional()],
    )
    description = StringField(
        "Beschreibung",
        validators=[
            Length(
                max=255,
                message="Beschreibung darf maximal 255 Zeichen lang sein.",
            ),
        ],
    )
    tags = StringField(
        "Tags (kommagetrennt)",
        validators=[
            Length(max=255),
        ],
    )
    submit = SubmitField("Speichern")

    def __init__(self, *args, accounts=None, categories=None, **kwargs):
        """Initialize form with dynamic account and category choices.

        Args:
            accounts: List of Account objects for dropdowns.
            categories: List of Category objects for dropdown.
        """
        super().__init__(*args, **kwargs)

        account_choices = [(0, "— Konto wählen —")]
        if accounts:
            account_choices += [(a.id, a.name) for a in accounts]
        self.account_id.choices = account_choices
        self.destination_account_id.choices = [(0, "— Kein Zielkonto —")] + (
            [(a.id, a.name) for a in accounts] if accounts else []
        )

        category_choices = [(0, "— Keine Kategorie —")]
        if categories:
            category_choices += [(c.id, c.name) for c in categories]
        self.category_id.choices = category_choices

    def validate(self, extra_validators=None):
        """Custom validation for destination_account requirement."""
        rv = super().validate(extra_validators=extra_validators)

        # destination_account_id is required for transfer and credit_card_payment
        if self.type.data in (
            TransactionType.transfer.value,
            TransactionType.credit_card_payment.value,
        ):
            if not self.destination_account_id.data or self.destination_account_id.data == 0:
                self.destination_account_id.errors.append(
                    "Zielkonto ist für Umbuchungen und Kreditkartenzahlungen erforderlich."
                )
                rv = False

        # account_id must be selected (not the placeholder)
        if not self.account_id.data or self.account_id.data == 0:
            self.account_id.errors.append("Konto ist erforderlich.")
            rv = False

        # Coerce 0 to None for optional fields
        if self.destination_account_id.data == 0:
            self.destination_account_id.data = None
        if self.category_id.data == 0:
            self.category_id.data = None

        return rv
