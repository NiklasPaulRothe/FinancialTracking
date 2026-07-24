"""WTForms form classes for the credits blueprint.

Validates: Requirements 11.1, 11.4
"""

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
    InputRequired,
    Length,
    NumberRange,
)
from flask_wtf import FlaskForm

from app.models.credit import CreditScope


class CreditCreateForm(FlaskForm):
    """Form for creating a new credit/loan.

    Validates: Requirement 11.1
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
    principal = DecimalField(
        "Darlehensbetrag",
        validators=[
            DataRequired(message="Darlehensbetrag ist erforderlich."),
            NumberRange(
                min=Decimal("0.01"),
                max=Decimal("999999999.99"),
                message="Darlehensbetrag muss zwischen 0,01 und 999.999.999,99 liegen.",
            ),
        ],
        places=2,
    )
    effective_yearly_rate = DecimalField(
        "Effektiver Jahreszins (als Dezimalzahl, z.B. 0.05 für 5%)",
        validators=[
            InputRequired(message="Effektiver Jahreszins ist erforderlich."),
            NumberRange(
                min=Decimal("0.0"),
                max=Decimal("1.0"),
                message="Effektiver Jahreszins muss zwischen 0,0 und 1,0 liegen.",
            ),
        ],
        places=6,
    )
    disbursement_date = DateField(
        "Auszahlungsdatum",
        validators=[
            DataRequired(message="Auszahlungsdatum ist erforderlich."),
        ],
    )
    interest_capitalization_day = IntegerField(
        "Zinskapitalisierungstag (1–28)",
        validators=[
            DataRequired(message="Zinskapitalisierungstag ist erforderlich."),
            NumberRange(
                min=1,
                max=28,
                message="Zinskapitalisierungstag muss zwischen 1 und 28 liegen.",
            ),
        ],
    )
    account_id = SelectField(
        "Verknüpftes Konto",
        coerce=int,
        validators=[DataRequired(message="Konto ist erforderlich.")],
    )
    scope = SelectField(
        "Zuordnung",
        choices=[
            (CreditScope.personal.value, "Persönlich"),
            (CreditScope.shared.value, "Gemeinsam"),
        ],
        validators=[DataRequired(message="Zuordnung ist erforderlich.")],
    )
    fixed_interest_amount = DecimalField(
        "Fester Zinsbetrag (optional, z.B. für Ratenkauf)",
        validators=[
            NumberRange(
                min=Decimal("0.00"),
                max=Decimal("999999999.99"),
                message="Fester Zinsbetrag muss zwischen 0,00 und 999.999.999,99 liegen.",
            ),
        ],
        places=2,
    )
    submit = SubmitField("Kredit erstellen")

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


class CreditRepayForm(FlaskForm):
    """Form for recording a repayment on a credit.

    Validates: Requirement 11.4
    """

    amount = DecimalField(
        "Rückzahlungsbetrag",
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
    submit = SubmitField("Rückzahlung buchen")



class CreditEditForm(FlaskForm):
    """Form for editing an existing credit/loan."""

    name = StringField(
        "Name",
        validators=[
            DataRequired(message="Name ist erforderlich."),
            Length(min=1, max=100),
        ],
    )
    remaining_balance = DecimalField(
        "Restschuld",
        validators=[
            DataRequired(message="Restschuld ist erforderlich."),
            NumberRange(
                min=Decimal("0.00"),
                max=Decimal("999999999.99"),
            ),
        ],
        places=2,
    )
    effective_yearly_rate = DecimalField(
        "Sollzinssatz (Dezimal, z.B. 0.0659 für 6,59%)",
        validators=[
            InputRequired(message="Zinssatz ist erforderlich."),
            NumberRange(min=Decimal("0.0"), max=Decimal("1.0")),
        ],
        places=6,
    )
    interest_capitalization_day = IntegerField(
        "Zinskapitalisierungstag (1–28)",
        validators=[
            DataRequired(message="Tag ist erforderlich."),
            NumberRange(min=1, max=28),
        ],
    )
    account_id = SelectField(
        "Verknüpftes Konto",
        coerce=int,
        validators=[DataRequired()],
    )
    scope = SelectField(
        "Zuordnung",
        choices=[
            (CreditScope.personal.value, "Persönlich"),
            (CreditScope.shared.value, "Gemeinsam"),
        ],
        validators=[DataRequired()],
    )
    fixed_interest_amount = DecimalField(
        "Fester Zinsbetrag (optional, z.B. für Ratenkauf)",
        validators=[
            NumberRange(
                min=Decimal("0.00"),
                max=Decimal("999999999.99"),
            ),
        ],
        places=2,
    )
    submit = SubmitField("Speichern")

    def __init__(self, *args, accounts=None, **kwargs):
        super().__init__(*args, **kwargs)
        account_choices = []
        if accounts:
            account_choices = [(a.id, a.name) for a in accounts]
        self.account_id.choices = account_choices
