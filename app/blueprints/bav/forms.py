"""WTForms form classes for the bAV blueprint.

Validates: Requirement 15.1
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
)
from flask_wtf import FlaskForm

from app.models.bav import BaVType


class BaVCreateForm(FlaskForm):
    """Form for creating a new bAV contract.

    Validates: Requirement 15.1
    """

    provider = StringField(
        "Anbieter",
        validators=[
            DataRequired(message="Anbieter ist erforderlich."),
            Length(
                min=1,
                max=100,
                message="Anbieter muss zwischen 1 und 100 Zeichen lang sein.",
            ),
        ],
    )
    type = SelectField(
        "Durchführungsweg",
        choices=[
            (BaVType.direktversicherung.value, "Direktversicherung"),
            (BaVType.pensionskasse.value, "Pensionskasse"),
            (BaVType.pensionsfonds.value, "Pensionsfonds"),
            (BaVType.direktzusage.value, "Direktzusage"),
            (BaVType.unterstuetzungskasse.value, "Unterstützungskasse"),
        ],
        validators=[DataRequired(message="Durchführungsweg ist erforderlich.")],
    )
    start_date = DateField(
        "Vertragsbeginn",
        validators=[
            DataRequired(message="Vertragsbeginn ist erforderlich."),
        ],
    )
    employee_contribution_monthly = DecimalField(
        "Arbeitnehmer-Beitrag (monatlich, €)",
        validators=[
            DataRequired(message="Arbeitnehmer-Beitrag ist erforderlich."),
            NumberRange(
                min=Decimal("0.01"),
                max=Decimal("50000.00"),
                message="Arbeitnehmer-Beitrag muss zwischen 0,01 und 50.000,00 € liegen.",
            ),
        ],
        places=2,
    )
    employer_contribution_monthly = DecimalField(
        "Arbeitgeber-Beitrag (monatlich, €)",
        validators=[
            DataRequired(message="Arbeitgeber-Beitrag ist erforderlich."),
            NumberRange(
                min=Decimal("0.00"),
                max=Decimal("50000.00"),
                message="Arbeitgeber-Beitrag muss zwischen 0,00 und 50.000,00 € liegen.",
            ),
        ],
        places=2,
        default=Decimal("0.00"),
    )
    submit = SubmitField("bAV-Vertrag anlegen")
