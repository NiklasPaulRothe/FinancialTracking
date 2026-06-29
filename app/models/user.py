"""User model for Haushaltsbuch.

Defines the User table with authentication fields, personal preferences,
and retirement/tax configuration columns.

Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7
"""

from datetime import datetime, timezone
from decimal import Decimal

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from app.extensions import db, login_manager


class User(UserMixin, db.Model):
    """Application user representing one member of the 2-person household."""

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(
        db.String(30),
        unique=True,
        nullable=False,
        index=True,
    )
    email = db.Column(
        db.String(255),
        unique=True,
        nullable=False,
        index=True,
    )
    password_hash = db.Column(db.String(255), nullable=False)
    income_day = db.Column(db.Integer, nullable=False)
    shared_income_day = db.Column(db.Integer, nullable=True)
    household_split_account_id = db.Column(db.Integer, nullable=True)
    household_split_tags = db.Column(db.String(500), nullable=True)  # JSON: {"person1": "Paul", "person2": "Jessy", "shared": "Geteilt"}
    date_format = db.Column(
        db.String(10), nullable=False, server_default="DD.MM.YYYY", default="DD.MM.YYYY"
    )
    marginal_tax_rate = db.Column(
        db.Numeric(5, 4), nullable=False, server_default="0.0", default=Decimal("0.0")
    )
    social_security_rate = db.Column(
        db.Numeric(5, 4), nullable=False, server_default="0.0", default=Decimal("0.0")
    )
    assumed_annual_return = db.Column(
        db.Numeric(5, 4), nullable=False, server_default="0.07", default=Decimal("0.07")
    )
    target_retirement_age = db.Column(
        db.Integer, nullable=False, server_default="67", default=67
    )
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        db.CheckConstraint(
            "income_day >= 1 AND income_day <= 31",
            name="ck_users_income_day_range",
        ),
        db.CheckConstraint(
            "marginal_tax_rate >= 0.0 AND marginal_tax_rate <= 1.0",
            name="ck_users_marginal_tax_rate_range",
        ),
        db.CheckConstraint(
            "social_security_rate >= 0.0 AND social_security_rate <= 1.0",
            name="ck_users_social_security_rate_range",
        ),
    )

    def __init__(self, **kwargs):
        """Initialize User with Python-level defaults for optional fields."""
        kwargs.setdefault("date_format", "DD.MM.YYYY")
        kwargs.setdefault("marginal_tax_rate", Decimal("0.0"))
        kwargs.setdefault("social_security_rate", Decimal("0.0"))
        kwargs.setdefault("assumed_annual_return", Decimal("0.07"))
        kwargs.setdefault("target_retirement_age", 67)
        kwargs.setdefault("created_at", datetime.now(timezone.utc))
        super().__init__(**kwargs)

    def set_password(self, password: str) -> None:
        """Hash and store the user's password."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        """Verify a plaintext password against the stored hash."""
        return check_password_hash(self.password_hash, password)

    def __repr__(self) -> str:
        return f"<User {self.username!r}>"


@login_manager.user_loader
def load_user(user_id: str) -> User | None:
    """Flask-Login callback to reload a user from the session."""
    return db.session.get(User, int(user_id))
