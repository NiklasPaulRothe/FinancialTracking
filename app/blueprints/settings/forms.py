"""WTForms form classes for the settings blueprint.

German-labelled forms for user preferences and password change.

Validates: Requirements 25.1, 25.2, 25.3, 25.5, 25.6, 25.7
"""

from wtforms import (
    IntegerField,
    SelectField,
    DecimalField,
    PasswordField,
    SubmitField,
)
from wtforms.validators import (
    DataRequired,
    NumberRange,
    Length,
    EqualTo,
)
from flask_wtf import FlaskForm


class SettingsForm(FlaskForm):
    """Form for editing user preferences.

    Validates: Requirements 25.1, 25.2, 25.3, 25.7
    """

    income_day = IntegerField(
        "Gehaltseingang (Tag des Monats)",
        validators=[
            DataRequired(message="Gehaltseingang ist erforderlich."),
            NumberRange(
                min=1,
                max=31,
                message="Gehaltseingang muss zwischen 1 und 31 liegen.",
            ),
        ],
    )
    date_format = SelectField(
        "Datumsformat",
        choices=[
            ("DD.MM.YYYY", "DD.MM.YYYY"),
            ("YYYY-MM-DD", "YYYY-MM-DD"),
            ("MM/DD/YYYY", "MM/DD/YYYY"),
        ],
        validators=[DataRequired(message="Datumsformat ist erforderlich.")],
    )
    marginal_tax_rate = DecimalField(
        "Grenzsteuersatz",
        validators=[
            DataRequired(message="Grenzsteuersatz ist erforderlich."),
            NumberRange(
                min=0.0,
                max=1.0,
                message="Grenzsteuersatz muss zwischen 0,0 und 1,0 liegen.",
            ),
        ],
        places=4,
    )
    social_security_rate = DecimalField(
        "Sozialversicherungssatz",
        validators=[
            DataRequired(message="Sozialversicherungssatz ist erforderlich."),
            NumberRange(
                min=0.0,
                max=1.0,
                message="Sozialversicherungssatz muss zwischen 0,0 und 1,0 liegen.",
            ),
        ],
        places=4,
    )
    assumed_annual_return = DecimalField(
        "Angenommene jährliche Rendite",
        validators=[
            DataRequired(message="Angenommene jährliche Rendite ist erforderlich."),
            NumberRange(
                min=0.0,
                max=1.0,
                message="Angenommene jährliche Rendite muss zwischen 0,0 und 1,0 liegen.",
            ),
        ],
        places=4,
    )
    target_retirement_age = IntegerField(
        "Ziel-Rentenalter",
        validators=[
            DataRequired(message="Ziel-Rentenalter ist erforderlich."),
            NumberRange(
                min=18,
                max=100,
                message="Ziel-Rentenalter muss zwischen 18 und 100 liegen.",
            ),
        ],
    )
    submit = SubmitField("Einstellungen speichern")


class ChangePasswordForm(FlaskForm):
    """Form for changing the user password.

    Validates: Requirements 25.5, 25.6
    """

    current_password = PasswordField(
        "Aktuelles Passwort",
        validators=[
            DataRequired(message="Aktuelles Passwort ist erforderlich."),
        ],
    )
    new_password = PasswordField(
        "Neues Passwort",
        validators=[
            DataRequired(message="Neues Passwort ist erforderlich."),
            Length(
                min=8,
                message="Neues Passwort muss mindestens 8 Zeichen lang sein.",
            ),
        ],
    )
    confirm_password = PasswordField(
        "Neues Passwort bestätigen",
        validators=[
            DataRequired(message="Bitte bestätigen Sie das neue Passwort."),
            EqualTo(
                "new_password",
                message="Passwörter stimmen nicht überein.",
            ),
        ],
    )
    submit = SubmitField("Passwort ändern")
