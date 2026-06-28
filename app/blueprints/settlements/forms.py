"""WTForms form classes for the settlements blueprint.

Validates: Requirements 12.1, 12.2
"""

from decimal import Decimal

from wtforms import DateField, DecimalField, SubmitField
from wtforms.validators import DataRequired, NumberRange
from flask_wtf import FlaskForm


class SettlementCreateForm(FlaskForm):
    """Form for creating a new settlement payment.

    Validates: Requirement 12.2
    The from_user is always the current user and to_user is the partner,
    so only amount and date are needed.
    """

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
        validators=[
            DataRequired(message="Datum ist erforderlich."),
        ],
    )
    submit = SubmitField("Ausgleich erstellen")
