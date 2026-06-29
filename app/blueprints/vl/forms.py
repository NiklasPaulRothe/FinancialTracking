"""WTForms form classes for the VL blueprint.

Validates: Requirements 16.1
"""

from decimal import Decimal

from wtforms import (
    DateField,
    DecimalField,
    StringField,
    SubmitField,
)
from wtforms.validators import (
    DataRequired,
    InputRequired,
    Length,
    NumberRange,
    Optional,
)
from flask_wtf import FlaskForm


class VLCreateForm(FlaskForm):
    """Form for creating a new VL contract.

    Instead of selecting an existing ETF position, the user provides the
    ISIN of the ETF. The system will auto-create an ETFPosition if one
    with that ISIN doesn't already exist for the user.

    Validates: Requirement 16.1
    """

    name = StringField(
        "Vertragsname",
        validators=[
            DataRequired(message="Name ist erforderlich."),
            Length(min=1, max=100, message="Name darf maximal 100 Zeichen lang sein."),
        ],
    )
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
    etf_isin = StringField(
        "ETF ISIN",
        validators=[
            Optional(),
            Length(max=12, message="ISIN darf maximal 12 Zeichen lang sein."),
        ],
    )
    etf_name = StringField(
        "ETF Name",
        validators=[
            Optional(),
            Length(max=200, message="ETF-Name darf maximal 200 Zeichen lang sein."),
        ],
    )
    etf_ticker = StringField(
        "ETF Ticker (z.B. EUNL)",
        validators=[
            Optional(),
            Length(max=10, message="Ticker darf maximal 10 Zeichen lang sein."),
        ],
    )
    etf_exchange = StringField(
        "Börse (z.B. DE, F, L)",
        validators=[
            Optional(),
            Length(max=10, message="Börse darf maximal 10 Zeichen lang sein."),
        ],
        default="DE",
    )
    etf_price = DecimalField(
        "Aktueller Kurs (€, falls Kursabfrage fehlschlägt)",
        validators=[
            Optional(),
            NumberRange(
                min=Decimal("0.0001"),
                max=Decimal("999999.9999"),
                message="Kurs muss positiv sein.",
            ),
        ],
        places=4,
    )
    sparzulage_rate = DecimalField(
        "Arbeitnehmer-Sparzulage (%)",
        validators=[
            InputRequired(message="Sparzulage-Rate ist erforderlich."),
            NumberRange(
                min=Decimal("0.0000"),
                max=Decimal("1.0000"),
                message="Sparzulage-Rate muss zwischen 0,0 und 1,0 (= 100%) liegen.",
            ),
        ],
        places=4,
        default=Decimal("0.0000"),
    )
    annual_eligible_max = DecimalField(
        "Max. förderfähiger Jahresbetrag (€)",
        validators=[
            InputRequired(message="Förderfähiger Jahresbetrag ist erforderlich."),
            NumberRange(
                min=Decimal("0.00"),
                max=Decimal("99999.99"),
                message="Förderfähiger Betrag muss zwischen 0,00 und 99.999,99 € liegen.",
            ),
        ],
        places=2,
        default=Decimal("0.00"),
    )
    submit = SubmitField("VL-Vertrag anlegen")
