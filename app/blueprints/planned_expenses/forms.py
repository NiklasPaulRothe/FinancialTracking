"""WTForms form classes for the planned expenses blueprint.

Validates: Requirements 9.1, 9.6
"""

from decimal import Decimal

from wtforms import (
    BooleanField,
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

from app.models.planned_expense import PlannedExpenseScope


class PlannedExpenseCreateForm(FlaskForm):
    """Form for creating a new planned expense.

    Validates: Requirements 9.1, 9.6
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
    amount_exact = DecimalField(
        "Genauer Betrag",
        validators=[
            Optional(),
            NumberRange(
                min=Decimal("0.01"),
                max=Decimal("999999999.99"),
                message="Betrag muss zwischen 0,01 und 999.999.999,99 liegen.",
            ),
        ],
        places=2,
    )
    amount_min = DecimalField(
        "Mindestbetrag",
        validators=[
            Optional(),
            NumberRange(
                min=Decimal("0.01"),
                max=Decimal("999999999.99"),
                message="Mindestbetrag muss zwischen 0,01 und 999.999.999,99 liegen.",
            ),
        ],
        places=2,
    )
    amount_max = DecimalField(
        "Höchstbetrag",
        validators=[
            Optional(),
            NumberRange(
                min=Decimal("0.01"),
                max=Decimal("999999999.99"),
                message="Höchstbetrag muss zwischen 0,01 und 999.999.999,99 liegen.",
            ),
        ],
        places=2,
    )
    scope = SelectField(
        "Zuordnung",
        choices=[
            (PlannedExpenseScope.personal.value, "Persönlich"),
            (PlannedExpenseScope.shared.value, "Gemeinsam"),
        ],
        validators=[DataRequired(message="Zuordnung ist erforderlich.")],
    )
    account_id = SelectField(
        "Konto (optional)",
        coerce=int,
        validators=[Optional()],
    )
    blocking = BooleanField(
        "Verfügbaren Betrag blockieren",
        default=True,
    )
    submit = SubmitField("Geplante Ausgabe erstellen")

    def __init__(self, *args, accounts=None, **kwargs):
        """Initialize form with dynamic account choices.

        Args:
            accounts: List of Account objects for the dropdown.
        """
        super().__init__(*args, **kwargs)

        account_choices = [(0, "— Kein Konto —")]
        if accounts:
            account_choices += [(a.id, a.name) for a in accounts]
        self.account_id.choices = account_choices

    def validate(self, extra_validators=None):
        """Custom validation for planned expense fields.

        Validates: Requirement 9.6 — amount_min must be <= amount_max
        """
        rv = super().validate(extra_validators=extra_validators)

        # Coerce 0 to None for optional account
        if self.account_id.data == 0:
            self.account_id.data = None

        # Validate range: amount_min <= amount_max
        if self.amount_min.data and self.amount_max.data:
            if self.amount_min.data > self.amount_max.data:
                self.amount_min.errors.append(
                    "Mindestbetrag darf nicht größer als Höchstbetrag sein."
                )
                rv = False

        return rv


class PlannedExpenseEditForm(FlaskForm):
    """Form for editing an existing planned expense.

    Validates: Requirements 9.5, 9.6
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
    amount_exact = DecimalField(
        "Genauer Betrag",
        validators=[
            Optional(),
            NumberRange(
                min=Decimal("0.01"),
                max=Decimal("999999999.99"),
                message="Betrag muss zwischen 0,01 und 999.999.999,99 liegen.",
            ),
        ],
        places=2,
    )
    amount_min = DecimalField(
        "Mindestbetrag",
        validators=[
            Optional(),
            NumberRange(
                min=Decimal("0.01"),
                max=Decimal("999999999.99"),
                message="Mindestbetrag muss zwischen 0,01 und 999.999.999,99 liegen.",
            ),
        ],
        places=2,
    )
    amount_max = DecimalField(
        "Höchstbetrag",
        validators=[
            Optional(),
            NumberRange(
                min=Decimal("0.01"),
                max=Decimal("999999999.99"),
                message="Höchstbetrag muss zwischen 0,01 und 999.999.999,99 liegen.",
            ),
        ],
        places=2,
    )
    scope = SelectField(
        "Zuordnung",
        choices=[
            (PlannedExpenseScope.personal.value, "Persönlich"),
            (PlannedExpenseScope.shared.value, "Gemeinsam"),
        ],
        validators=[DataRequired(message="Zuordnung ist erforderlich.")],
    )
    account_id = SelectField(
        "Konto (optional)",
        coerce=int,
        validators=[Optional()],
    )
    blocking = BooleanField(
        "Verfügbaren Betrag blockieren",
        default=True,
    )
    submit = SubmitField("Speichern")

    def __init__(self, *args, accounts=None, **kwargs):
        """Initialize form with dynamic account choices.

        Args:
            accounts: List of Account objects for the dropdown.
        """
        super().__init__(*args, **kwargs)

        account_choices = [(0, "— Kein Konto —")]
        if accounts:
            account_choices += [(a.id, a.name) for a in accounts]
        self.account_id.choices = account_choices

    def validate(self, extra_validators=None):
        """Custom validation for planned expense fields.

        Validates: Requirement 9.6 — amount_min must be <= amount_max
        """
        rv = super().validate(extra_validators=extra_validators)

        # Coerce 0 to None for optional account
        if self.account_id.data == 0:
            self.account_id.data = None

        # Validate range: amount_min <= amount_max
        if self.amount_min.data and self.amount_max.data:
            if self.amount_min.data > self.amount_max.data:
                self.amount_min.errors.append(
                    "Mindestbetrag darf nicht größer als Höchstbetrag sein."
                )
                rv = False

        return rv
