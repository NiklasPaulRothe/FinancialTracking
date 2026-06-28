"""WTForms form classes for the saving goals blueprint.

Validates: Requirements 10.1, 10.2
"""

from decimal import Decimal

from wtforms import (
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

from app.models.budget import SavingGoalScope


class SavingGoalCreateForm(FlaskForm):
    """Form for creating a new saving goal.

    Validates: Requirement 10.1
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
    target_amount = DecimalField(
        "Zielbetrag (optional)",
        validators=[
            Optional(),
            NumberRange(
                min=Decimal("0.01"),
                max=Decimal("999999999.99"),
                message="Zielbetrag muss zwischen 0,01 und 999.999.999,99 liegen.",
            ),
        ],
        places=2,
    )
    scope = SelectField(
        "Zuordnung",
        choices=[
            (SavingGoalScope.personal.value, "Persönlich"),
            (SavingGoalScope.shared.value, "Gemeinsam"),
        ],
        validators=[DataRequired(message="Zuordnung ist erforderlich.")],
    )
    submit = SubmitField("Sparziel erstellen")


class SavingContributionForm(FlaskForm):
    """Form for adding a contribution to a saving goal.

    Validates: Requirement 10.2
    """

    account_id = SelectField(
        "Konto",
        coerce=int,
        validators=[DataRequired(message="Konto ist erforderlich.")],
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
    submit = SubmitField("Beitrag hinzufügen")

    def __init__(self, *args, accounts=None, **kwargs):
        """Initialize form with dynamic account choices.

        Args:
            accounts: List of Account objects for the dropdown.
        """
        super().__init__(*args, **kwargs)

        account_choices = [(0, "— Konto wählen —")]
        if accounts:
            account_choices += [(a.id, a.name) for a in accounts]
        self.account_id.choices = account_choices

    def validate(self, extra_validators=None):
        """Custom validation — account must be selected."""
        rv = super().validate(extra_validators=extra_validators)

        if not self.account_id.data or self.account_id.data == 0:
            self.account_id.errors.append("Konto ist erforderlich.")
            rv = False

        return rv
