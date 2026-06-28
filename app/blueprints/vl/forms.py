"""WTForms form classes for the VL blueprint.

Validates: Requirements 16.1
"""

from decimal import Decimal

from wtforms import (
    DateField,
    DecimalField,
    SelectField,
    SubmitField,
)
from wtforms.validators import (
    DataRequired,
    NumberRange,
    Optional,
)
from flask_wtf import FlaskForm


class VLCreateForm(FlaskForm):
    """Form for creating a new VL contract.

    Validates: Requirement 16.1
    """

    employer_contribution_monthly = DecimalField(
        "Arbeitgeber-Beitrag (monatlich, €)",
        validators=[
            DataRequired(message="Arbeitgeber-Beitrag ist erforderlich."),
            NumberRange(
                min=Decimal("0.01"),
                max=Decimal("50000.00"),
                message="Arbeitgeber-Beitrag muss zwischen 0,01 und 50.000,00 € liegen.",
            ),
        ],
        places=2,
    )
    employee_contribution_monthly = DecimalField(
        "Arbeitnehmer-Beitrag (monatlich, €)",
        validators=[
            Optional(),
            NumberRange(
                min=Decimal("0.00"),
                max=Decimal("50000.00"),
                message="Arbeitnehmer-Beitrag muss zwischen 0,00 und 50.000,00 € liegen.",
            ),
        ],
        places=2,
        default=Decimal("0.00"),
    )
    start_date = DateField(
        "Vertragsbeginn",
        validators=[
            DataRequired(message="Vertragsbeginn ist erforderlich."),
        ],
    )
    lock_up_end_date = DateField(
        "Ende der Sperrfrist",
        validators=[
            DataRequired(message="Ende der Sperrfrist ist erforderlich."),
        ],
    )
    etf_position_id = SelectField(
        "ETF-Position (optional)",
        coerce=int,
        validators=[Optional()],
    )
    sparzulage_rate = DecimalField(
        "Arbeitnehmer-Sparzulage (%)",
        validators=[
            DataRequired(message="Sparzulage-Rate ist erforderlich."),
            NumberRange(
                min=Decimal("0.0000"),
                max=Decimal("1.0000"),
                message="Sparzulage-Rate muss zwischen 0,0 und 1,0 (= 100%) liegen.",
            ),
        ],
        places=4,
        default=Decimal("0.2000"),
    )
    annual_eligible_max = DecimalField(
        "Max. förderfähiger Jahresbetrag (€)",
        validators=[
            DataRequired(message="Förderfähiger Jahresbetrag ist erforderlich."),
            NumberRange(
                min=Decimal("0.01"),
                max=Decimal("99999.99"),
                message="Förderfähiger Betrag muss zwischen 0,01 und 99.999,99 € liegen.",
            ),
        ],
        places=2,
        default=Decimal("400.00"),
    )
    submit = SubmitField("VL-Vertrag anlegen")

    def __init__(self, *args, etf_positions=None, **kwargs):
        """Initialize form with dynamic ETF position choices.

        Args:
            etf_positions: List of ETFPosition objects for the dropdown.
        """
        super().__init__(*args, **kwargs)

        position_choices = [(0, "— Keine ETF-Position —")]
        if etf_positions:
            position_choices += [
                (p.id, f"{p.name} ({p.ticker}.{p.exchange_suffix})")
                for p in etf_positions
            ]
        self.etf_position_id.choices = position_choices
