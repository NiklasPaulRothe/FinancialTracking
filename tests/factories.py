"""Factory Boy factories for generating test data.

These factories create model instances with sensible defaults for testing.
All factories use the SQLAlchemy session provided by the db_session fixture.
"""

import factory
from datetime import date, datetime
from decimal import Decimal

from app.extensions import db
from app.models.user import User
from app.models.account import Account
from app.models.transaction import Transaction


class BaseFactory(factory.alchemy.SQLAlchemyModelFactory):
    """Base factory with shared SQLAlchemy session configuration."""

    class Meta:
        abstract = True
        sqlalchemy_session = None  # Set dynamically via session fixture
        sqlalchemy_session_persistence = "flush"

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        """Override create to use the current scoped session."""
        cls._meta.sqlalchemy_session = db.session
        return super()._create(model_class, *args, **kwargs)


class UserFactory(BaseFactory):
    """Factory for User model.

    Generates unique usernames and emails with reasonable defaults
    for financial settings.
    """

    class Meta:
        model = User

    username = factory.Sequence(lambda n: f"testuser{n}")
    email = factory.LazyAttribute(lambda obj: f"{obj.username}@example.com")
    password_hash = factory.LazyFunction(
        lambda: "pbkdf2:sha256:600000$salt$fakehashforspeed"
    )
    income_day = 25
    date_format = "DD.MM.YYYY"
    marginal_tax_rate = Decimal("0.4200")
    social_security_rate = Decimal("0.2050")
    assumed_annual_return = Decimal("0.0700")
    target_retirement_age = 67
    created_at = factory.LazyFunction(datetime.utcnow)


class AccountFactory(BaseFactory):
    """Factory for Account model.

    Creates a personal spending account by default, owned by a generated user.
    """

    class Meta:
        model = Account

    name = factory.Sequence(lambda n: f"Test Account {n}")
    type = "spending"
    scope = "personal"
    balance = Decimal("0.00")
    active = True
    visible_to_partner = True
    owner = factory.SubFactory(UserFactory)
    created_at = factory.LazyFunction(datetime.utcnow)


class TransactionFactory(BaseFactory):
    """Factory for Transaction model.

    Creates a personal expense transaction by default with a valid amount.
    """

    class Meta:
        model = Transaction

    type = "expense"
    amount = Decimal("50.00")
    date = factory.LazyFunction(date.today)
    scope = "personal"
    posted = True
    account = factory.SubFactory(AccountFactory)
    user = factory.LazyAttribute(lambda obj: obj.account.owner)
    created_at = factory.LazyFunction(datetime.utcnow)
