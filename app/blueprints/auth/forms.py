"""WTForms form classes for the authentication blueprint.

Validates: Requirements 1.2, 1.3, 1.4, 1.5
"""

from wtforms import StringField, PasswordField, BooleanField, IntegerField, SubmitField
from wtforms.validators import (
    DataRequired,
    Email,
    Length,
    NumberRange,
    Regexp,
    EqualTo,
)
from flask_wtf import FlaskForm


class LoginForm(FlaskForm):
    """Login form with username and password fields."""

    username = StringField(
        "Benutzername",
        validators=[DataRequired(message="Benutzername ist erforderlich.")],
    )
    password = PasswordField(
        "Passwort",
        validators=[DataRequired(message="Passwort ist erforderlich.")],
    )
    remember_me = BooleanField("Angemeldet bleiben")
    submit = SubmitField("Anmelden")


class RegistrationForm(FlaskForm):
    """Registration form with full validation for username, email, password, and income day."""

    username = StringField(
        "Benutzername",
        validators=[
            DataRequired(message="Benutzername ist erforderlich."),
            Length(
                min=3,
                max=30,
                message="Benutzername muss zwischen 3 und 30 Zeichen lang sein.",
            ),
            Regexp(
                r"^[a-zA-Z0-9_]{3,30}$",
                message="Benutzername darf nur Buchstaben, Ziffern und Unterstriche enthalten.",
            ),
        ],
    )
    email = StringField(
        "E-Mail",
        validators=[
            DataRequired(message="E-Mail ist erforderlich."),
            Email(message="Bitte geben Sie eine gültige E-Mail-Adresse ein."),
        ],
    )
    password = PasswordField(
        "Passwort",
        validators=[
            DataRequired(message="Passwort ist erforderlich."),
            Length(
                min=8,
                message="Passwort muss mindestens 8 Zeichen lang sein.",
            ),
        ],
    )
    password_confirm = PasswordField(
        "Passwort bestätigen",
        validators=[
            DataRequired(message="Bitte bestätigen Sie das Passwort."),
            EqualTo("password", message="Passwörter stimmen nicht überein."),
        ],
    )
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
    submit = SubmitField("Registrieren")
