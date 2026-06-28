"""WTForms form classes for the accounts blueprint.

Validates: Requirements 2.1, 2.2, 2.9
"""

from decimal import Decimal

from wtforms import (
    StringField,
    SelectField,
    BooleanField,
    DecimalField,
    IntegerField,
    SubmitField,
)
from wtforms.validators import (
    DataRequired,
    Length,
    NumberRange,
    Optional,
)
from flask_wtf import FlaskForm

from app.models.account import AccountType, AccountScope


class AccountCreateForm(FlaskForm):
    """Form for creating a new account.

    Validates: Requirement 2.1
    """

    name = StringField(
        "Name",
        validators=[
            DataRequired(message="Name ist erforderlich."),
            Length(
                min=1,
                max=50,
                message="Name muss zwischen 1 und 50 Zeichen lang sein.",
            ),
        ],
    )
    type = SelectField(
        "Kontotyp",
        choices=[
            (AccountType.spending.value, "Girokonto"),
            (AccountType.saving.value, "Sparkonto"),
            (AccountType.credit_card.value, "Kreditkarte"),
        ],
        validators=[DataRequired(message="Kontotyp ist erforderlich.")],
    )
    scope = SelectField(
        "Zuordnung",
        choices=[
            (AccountScope.personal.value, "Persönlich"),
            (AccountScope.shared.value, "Gemeinsam"),
        ],
        validators=[DataRequired(message="Zuordnung ist erforderlich.")],
    )
    institute = StringField(
        "Institut",
        validators=[
            Length(max=100, message="Institut darf maximal 100 Zeichen lang sein."),
        ],
    )
    starting_balance = DecimalField(
        "Startsaldo",
        validators=[Optional()],
        places=2,
        default=Decimal("0.00"),
    )
    visible_to_partner = BooleanField("Für Partner sichtbar", default=True)
    max_overdraft = DecimalField(
        "Maximaler Überziehungsrahmen",
        validators=[Optional()],
        places=2,
    )
    credit_limit = DecimalField(
        "Kreditlimit",
        validators=[Optional()],
        places=2,
    )
    statement_closing_day = IntegerField(
        "Abrechnungstag",
        validators=[Optional()],
    )
    payment_due_day = IntegerField(
        "Fälligkeitstag",
        validators=[Optional()],
    )
    submit = SubmitField("Konto erstellen")

    def validate(self, extra_validators=None):
        """Override validate to add credit card field validation."""
        rv = super().validate(extra_validators=extra_validators)

        # Only validate credit card fields when type is credit_card
        if self.type.data == AccountType.credit_card.value:
            # Coerce credit_limit to Decimal if it's a string
            credit_limit = self.credit_limit.data
            if credit_limit is not None and isinstance(credit_limit, str):
                try:
                    credit_limit = Decimal(credit_limit)
                    self.credit_limit.data = credit_limit
                except Exception:
                    credit_limit = None

            if credit_limit is None:
                self.credit_limit.errors.append(
                    "Kreditlimit ist für Kreditkarten erforderlich."
                )
                rv = False
            elif (
                credit_limit < Decimal("0.01")
                or credit_limit > Decimal("999999999.99")
            ):
                self.credit_limit.errors.append(
                    "Kreditlimit muss zwischen 0,01 und 999.999.999,99 liegen."
                )
                rv = False

            # Coerce statement_closing_day to int if it's a string
            closing_day = self.statement_closing_day.data
            if closing_day is not None and isinstance(closing_day, str):
                try:
                    closing_day = int(closing_day)
                    self.statement_closing_day.data = closing_day
                except (ValueError, TypeError):
                    closing_day = None

            if closing_day is None:
                self.statement_closing_day.errors.append(
                    "Abrechnungstag ist für Kreditkarten erforderlich."
                )
                rv = False
            elif closing_day < 1 or closing_day > 28:
                self.statement_closing_day.errors.append(
                    "Abrechnungstag muss zwischen 1 und 28 liegen."
                )
                rv = False

            # Coerce payment_due_day to int if it's a string
            due_day = self.payment_due_day.data
            if due_day is not None and isinstance(due_day, str):
                try:
                    due_day = int(due_day)
                    self.payment_due_day.data = due_day
                except (ValueError, TypeError):
                    due_day = None

            if due_day is None:
                self.payment_due_day.errors.append(
                    "Fälligkeitstag ist für Kreditkarten erforderlich."
                )
                rv = False
            elif due_day < 1 or due_day > 28:
                self.payment_due_day.errors.append(
                    "Fälligkeitstag muss zwischen 1 und 28 liegen."
                )
                rv = False

        return rv


class AccountEditForm(FlaskForm):
    """Form for editing an existing account.

    Validates: Requirement 2.2
    Editable fields: name, institute, visible_to_partner.
    For credit_card type: credit_limit, statement_closing_day, payment_due_day.
    """

    name = StringField(
        "Name",
        validators=[
            DataRequired(message="Name ist erforderlich."),
            Length(
                min=1,
                max=50,
                message="Name muss zwischen 1 und 50 Zeichen lang sein.",
            ),
        ],
    )
    institute = StringField(
        "Institut",
        validators=[
            Length(max=100, message="Institut darf maximal 100 Zeichen lang sein."),
        ],
    )
    starting_balance = DecimalField(
        "Startsaldo",
        validators=[Optional()],
        places=2,
    )
    visible_to_partner = BooleanField("Für Partner sichtbar", default=True)
    credit_limit = DecimalField(
        "Kreditlimit",
        validators=[
            Optional(),
            NumberRange(
                min=Decimal("0.01"),
                max=Decimal("999999999.99"),
                message="Kreditlimit muss zwischen 0,01 und 999.999.999,99 liegen.",
            ),
        ],
        places=2,
    )
    statement_closing_day = IntegerField(
        "Abrechnungstag",
        validators=[
            Optional(),
            NumberRange(
                min=1,
                max=28,
                message="Abrechnungstag muss zwischen 1 und 28 liegen.",
            ),
        ],
    )
    payment_due_day = IntegerField(
        "Fälligkeitstag",
        validators=[
            Optional(),
            NumberRange(
                min=1,
                max=28,
                message="Fälligkeitstag muss zwischen 1 und 28 liegen.",
            ),
        ],
    )
    submit = SubmitField("Speichern")
