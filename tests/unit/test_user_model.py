"""Unit tests for the User model.

Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7
"""

import pytest
from decimal import Decimal

from app.models.user import User


class TestUserModel:
    """Tests for User model behaviour (no DB required)."""

    def test_set_and_check_password(self):
        """Password hashing and verification works correctly."""
        user = User(username="testuser", email="test@example.com", income_day=15)
        user.set_password("securepass123")

        assert user.password_hash is not None
        assert user.password_hash != "securepass123"
        assert user.check_password("securepass123") is True
        assert user.check_password("wrongpassword") is False

    def test_password_hash_differs_for_same_password(self):
        """Two users with the same password get different hashes."""
        user1 = User(username="user1", email="u1@example.com", income_day=1)
        user2 = User(username="user2", email="u2@example.com", income_day=1)
        user1.set_password("samepassword")
        user2.set_password("samepassword")

        assert user1.password_hash != user2.password_hash

    def test_default_values(self):
        """User model has correct default values for optional fields."""
        user = User(username="defaults", email="def@example.com", income_day=25)

        assert user.date_format == "DD.MM.YYYY"
        assert user.marginal_tax_rate == Decimal("0.0")
        assert user.social_security_rate == Decimal("0.0")
        assert user.assumed_annual_return == Decimal("0.07")
        assert user.target_retirement_age == 67

    def test_repr(self):
        """User repr includes username."""
        user = User(username="alice", email="alice@example.com", income_day=10)
        assert repr(user) == "<User 'alice'>"

    def test_user_mixin_properties(self):
        """UserMixin provides is_authenticated, is_active, get_id."""
        user = User(username="mixin", email="m@example.com", income_day=5)
        user.id = 42

        assert user.is_authenticated is True
        assert user.is_active is True
        assert user.get_id() == "42"
