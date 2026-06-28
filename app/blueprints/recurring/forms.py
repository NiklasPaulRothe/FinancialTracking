"""WTForms form classes for the recurring blueprint.

Validates: Requirements 5.1, 5.10
"""

from datetime import date
from decimal import Decimal

from wtforms import (
    DateField,
    DecimalField,
    IntegerField,
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

from app.models.transaction import (
    RecurringFrequency,
    TransactionScope,
    TransactionType,
)


class RecurringRuleCreateForm(FlaskForm):
    """Form for creating a new recurring rule.

    Validates: Requirements 5.1, 5.10
    """

    name = StringField(
        "Name",
        validators=[
            DataRequired(message="Name ist erforderlich."),
            Length(
                min=1,
                max=100,
                message="Name muss zwischen 1 und 100 Zeichen lang sein.",
            ),
        ],
    )
    type = SelectField(
        "Typ",
        choices=[
            (TransactionType.income.value, "Einnahme"),
            (TransactionType.expense.value, "Ausgabe"),
            (TransactionType.transfer.value, "Umbuchung"),
        ],
        validators=[DataRequired(message="Typ ist erforderlich.")],
    )
    frequency = SelectField(
        "Frequenz",
        choices=[
            (RecurringFrequency.daily.value, "Täglich"),
            (RecurringFrequency.weekly.value, "Wöchentlich"),
            (RecurringFrequency.monthly.value, "Monatlich"),
            (RecurringFrequency.quarterly.value, "Vierteljährlich"),
            (RecurringFrequency.yearly.value, "Jährlich"),
        ],
        validators=[DataRequired(message="Frequenz ist erforderlich.")],
    )
    interval = IntegerField(
        "Intervall",
        validators=[
            DataRequired(message="Intervall ist erforderlich."),
            NumberRange(
                min=1,
                max=365,
                message="Intervall muss zwischen 1 und 365 liegen.",
            ),
        ],
        default=1,
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
    next_due_date = DateField(
        "Nächstes Fälligkeitsdatum",
        validators=[DataRequired(message="Nächstes Fälligkeitsdatum ist erforderlich.")],
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
    submit = SubmitField("Dauerauftrag erstellen")

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
        """Custom validation for recurring rule fields."""
        rv = super().validate(extra_validators=extra_validators)

        # destination_account_id is required for transfer type
        if self.type.data == TransactionType.transfer.value:
            if not self.destination_account_id.data or self.destination_account_id.data == 0:
                self.destination_account_id.errors.append(
                    "Zielkonto ist für Umbuchungen erforderlich."
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


class RecurringRuleEditForm(FlaskForm):
    """Form for editing an existing recurring rule.

    Validates: Requirements 5.1, 5.10
    """

    name = StringField(
        "Name",
        validators=[
            DataRequired(message="Name ist erforderlich."),
            Length(
                min=1,
                max=100,
                message="Name muss zwischen 1 und 100 Zeichen lang sein.",
            ),
        ],
    )
    type = SelectField(
        "Typ",
        choices=[
            (TransactionType.income.value, "Einnahme"),
            (TransactionType.expense.value, "Ausgabe"),
            (TransactionType.transfer.value, "Umbuchung"),
        ],
        validators=[DataRequired(message="Typ ist erforderlich.")],
    )
    frequency = SelectField(
        "Frequenz",
        choices=[
            (RecurringFrequency.daily.value, "Täglich"),
            (RecurringFrequency.weekly.value, "Wöchentlich"),
            (RecurringFrequency.monthly.value, "Monatlich"),
            (RecurringFrequency.quarterly.value, "Vierteljährlich"),
            (RecurringFrequency.yearly.value, "Jährlich"),
        ],
        validators=[DataRequired(message="Frequenz ist erforderlich.")],
    )
    interval = IntegerField(
        "Intervall",
        validators=[
            DataRequired(message="Intervall ist erforderlich."),
            NumberRange(
                min=1,
                max=365,
                message="Intervall muss zwischen 1 und 365 liegen.",
            ),
        ],
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
    next_due_date = DateField(
        "Nächstes Fälligkeitsdatum",
        validators=[DataRequired(message="Nächstes Fälligkeitsdatum ist erforderlich.")],
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
        """Custom validation for recurring rule fields."""
        rv = super().validate(extra_validators=extra_validators)

        # destination_account_id is required for transfer type
        if self.type.data == TransactionType.transfer.value:
            if not self.destination_account_id.data or self.destination_account_id.data == 0:
                self.destination_account_id.errors.append(
                    "Zielkonto ist für Umbuchungen erforderlich."
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
