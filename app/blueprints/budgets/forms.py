"""WTForms form classes for the budgets blueprint.

Validates: Requirements 6.1, 6.7, 6.8
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

from app.models.budget import BudgetPeriod, BudgetScope


class BudgetCreateForm(FlaskForm):
    """Form for creating a new budget.

    Validates: Requirements 6.1, 6.8
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
    scope = SelectField(
        "Zuordnung",
        choices=[
            (BudgetScope.personal.value, "Persönlich"),
            (BudgetScope.shared.value, "Gemeinsam"),
        ],
        validators=[DataRequired(message="Zuordnung ist erforderlich.")],
    )
    category_id = SelectField(
        "Kategorie",
        coerce=int,
        validators=[Optional()],
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
    period = SelectField(
        "Zeitraum",
        choices=[
            (BudgetPeriod.weekly.value, "Wöchentlich"),
            (BudgetPeriod.monthly.value, "Monatlich"),
            (BudgetPeriod.quarterly.value, "Vierteljährlich"),
            (BudgetPeriod.yearly.value, "Jährlich"),
        ],
        validators=[DataRequired(message="Zeitraum ist erforderlich.")],
    )
    start_date = DateField(
        "Startdatum",
        validators=[DataRequired(message="Startdatum ist erforderlich.")],
        default=date.today,
    )
    submit = SubmitField("Budget erstellen")

    def __init__(self, *args, categories=None, **kwargs):
        """Initialize form with dynamic category choices.

        Args:
            categories: List of Category objects for dropdown.
        """
        super().__init__(*args, **kwargs)

        category_choices = [(0, "— Alle Kategorien (Gesamtbudget) —")]
        if categories:
            category_choices += [(c.id, c.name) for c in categories]
        self.category_id.choices = category_choices

    def validate(self, extra_validators=None):
        """Custom validation for budget fields."""
        rv = super().validate(extra_validators=extra_validators)

        # Coerce 0 to None for optional category
        if self.category_id.data == 0:
            self.category_id.data = None

        return rv


class BudgetEditForm(FlaskForm):
    """Form for editing an existing budget.

    Validates: Requirement 6.7
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
    scope = SelectField(
        "Zuordnung",
        choices=[
            (BudgetScope.personal.value, "Persönlich"),
            (BudgetScope.shared.value, "Gemeinsam"),
        ],
        validators=[DataRequired(message="Zuordnung ist erforderlich.")],
    )
    category_id = SelectField(
        "Kategorie",
        coerce=int,
        validators=[Optional()],
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
    period = SelectField(
        "Zeitraum",
        choices=[
            (BudgetPeriod.weekly.value, "Wöchentlich"),
            (BudgetPeriod.monthly.value, "Monatlich"),
            (BudgetPeriod.quarterly.value, "Vierteljährlich"),
            (BudgetPeriod.yearly.value, "Jährlich"),
        ],
        validators=[DataRequired(message="Zeitraum ist erforderlich.")],
    )
    start_date = DateField(
        "Startdatum",
        validators=[DataRequired(message="Startdatum ist erforderlich.")],
    )
    submit = SubmitField("Speichern")

    def __init__(self, *args, categories=None, **kwargs):
        """Initialize form with dynamic category choices.

        Args:
            categories: List of Category objects for dropdown.
        """
        super().__init__(*args, **kwargs)

        category_choices = [(0, "— Alle Kategorien (Gesamtbudget) —")]
        if categories:
            category_choices += [(c.id, c.name) for c in categories]
        self.category_id.choices = category_choices

    def validate(self, extra_validators=None):
        """Custom validation for budget fields."""
        rv = super().validate(extra_validators=extra_validators)

        # Coerce 0 to None for optional category
        if self.category_id.data == 0:
            self.category_id.data = None

        return rv
