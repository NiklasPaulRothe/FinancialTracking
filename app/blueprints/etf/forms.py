"""WTForms form classes for the ETF blueprint.

Validates: Requirements 13.1, 13.5, 13.6, 14.1
"""

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
    Regexp,
)
from flask_wtf import FlaskForm


class ETFPositionForm(FlaskForm):
    """Form for adding a new ETF position.

    Validates: Requirement 13.1
    """

    ticker = StringField(
        "Ticker",
        validators=[
            DataRequired(message="Ticker ist erforderlich."),
            Length(
                min=1,
                max=10,
                message="Ticker muss zwischen 1 und 10 Zeichen lang sein.",
            ),
            Regexp(
                r"^[A-Z0-9]+$",
                message="Ticker darf nur Großbuchstaben und Ziffern enthalten.",
            ),
        ],
    )
    exchange_suffix = StringField(
        "Börsen-Suffix",
        validators=[
            DataRequired(message="Börsen-Suffix ist erforderlich."),
            Length(
                min=1,
                max=10,
                message="Börsen-Suffix muss zwischen 1 und 10 Zeichen lang sein.",
            ),
        ],
    )
    name = StringField(
        "Name",
        validators=[
            DataRequired(message="Name ist erforderlich."),
            Length(
                min=1,
                max=200,
                message="Name muss zwischen 1 und 200 Zeichen lang sein.",
            ),
        ],
    )
    shares = DecimalField(
        "Anfangsanteile",
        validators=[
            DataRequired(message="Anteile sind erforderlich."),
            NumberRange(
                min=Decimal("0.000001"),
                message="Anteile müssen größer als 0 sein.",
            ),
        ],
        places=6,
    )
    average_buy_price = DecimalField(
        "Durchschnittlicher Kaufpreis",
        validators=[
            DataRequired(message="Durchschnittlicher Kaufpreis ist erforderlich."),
            NumberRange(
                min=Decimal("0.000001"),
                message="Durchschnittlicher Kaufpreis muss größer als 0 sein.",
            ),
        ],
        places=6,
    )
    submit = SubmitField("Position hinzufügen")


class ETFBuySellForm(FlaskForm):
    """Form for recording a buy or sell ETF transaction.

    Validates: Requirements 13.5, 13.6
    """

    shares_quantity = DecimalField(
        "Anzahl Anteile",
        validators=[
            DataRequired(message="Anzahl Anteile ist erforderlich."),
            NumberRange(
                min=Decimal("0.000001"),
                message="Anzahl Anteile muss größer als 0 sein.",
            ),
        ],
        places=6,
    )
    price_per_share = DecimalField(
        "Preis pro Anteil",
        validators=[
            DataRequired(message="Preis pro Anteil ist erforderlich."),
            NumberRange(
                min=Decimal("0.000001"),
                message="Preis pro Anteil muss größer als 0 sein.",
            ),
        ],
        places=6,
    )
    linked_account_id = SelectField(
        "Verknüpftes Konto (optional)",
        coerce=int,
        validators=[Optional()],
    )
    date = DateField(
        "Datum",
        validators=[
            DataRequired(message="Datum ist erforderlich."),
        ],
    )
    submit = SubmitField("Transaktion buchen")

    def __init__(self, *args, accounts=None, **kwargs):
        """Initialize form with dynamic account choices.

        Args:
            accounts: List of Account objects for the dropdown.
        """
        super().__init__(*args, **kwargs)

        account_choices = [(0, "— Kein Konto —")]
        if accounts:
            account_choices += [(a.id, a.name) for a in accounts]
        self.linked_account_id.choices = account_choices
