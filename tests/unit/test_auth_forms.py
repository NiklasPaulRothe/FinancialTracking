"""Unit tests for authentication forms.

Validates: Requirements 1.2, 1.3, 1.4, 1.5
"""

import pytest
from app import create_app
from app.blueprints.auth.forms import LoginForm, RegistrationForm


@pytest.fixture()
def req_app():
    """Create a minimal app for form testing (no DB needed)."""
    application = create_app("testing")
    return application


class TestLoginForm:
    """Tests for LoginForm validation."""

    def test_valid_login_form(self, req_app):
        """Login form accepts valid username and password."""
        with req_app.test_request_context():
            form = LoginForm(data={
                "username": "testuser",
                "password": "password123",
            })
            assert form.validate() is True

    def test_missing_username(self, req_app):
        """Login form rejects empty username."""
        with req_app.test_request_context():
            form = LoginForm(data={
                "username": "",
                "password": "password123",
            })
            assert form.validate() is False
            assert "username" in form.errors

    def test_missing_password(self, req_app):
        """Login form rejects empty password."""
        with req_app.test_request_context():
            form = LoginForm(data={
                "username": "testuser",
                "password": "",
            })
            assert form.validate() is False
            assert "password" in form.errors


class TestRegistrationForm:
    """Tests for RegistrationForm validation."""

    def test_valid_registration(self, req_app):
        """Registration form accepts valid input."""
        with req_app.test_request_context():
            form = RegistrationForm(data={
                "username": "alice_01",
                "email": "alice@example.com",
                "password": "securepass",
                "password_confirm": "securepass",
                "income_day": 15,
            })
            assert form.validate() is True

    def test_username_too_short(self, req_app):
        """Username must be at least 3 characters."""
        with req_app.test_request_context():
            form = RegistrationForm(data={
                "username": "ab",
                "email": "a@b.com",
                "password": "12345678",
                "password_confirm": "12345678",
                "income_day": 1,
            })
            assert form.validate() is False
            assert "username" in form.errors

    def test_username_too_long(self, req_app):
        """Username must be at most 30 characters."""
        with req_app.test_request_context():
            form = RegistrationForm(data={
                "username": "a" * 31,
                "email": "a@b.com",
                "password": "12345678",
                "password_confirm": "12345678",
                "income_day": 1,
            })
            assert form.validate() is False
            assert "username" in form.errors

    def test_username_invalid_characters(self, req_app):
        """Username rejects special characters (only alphanumeric + underscore)."""
        with req_app.test_request_context():
            form = RegistrationForm(data={
                "username": "user@name!",
                "email": "u@b.com",
                "password": "12345678",
                "password_confirm": "12345678",
                "income_day": 1,
            })
            assert form.validate() is False
            assert "username" in form.errors

    def test_invalid_email(self, req_app):
        """Registration rejects invalid email format."""
        with req_app.test_request_context():
            form = RegistrationForm(data={
                "username": "validuser",
                "email": "not-an-email",
                "password": "12345678",
                "password_confirm": "12345678",
                "income_day": 1,
            })
            assert form.validate() is False
            assert "email" in form.errors

    def test_password_too_short(self, req_app):
        """Password must be at least 8 characters."""
        with req_app.test_request_context():
            form = RegistrationForm(data={
                "username": "validuser",
                "email": "v@b.com",
                "password": "short",
                "password_confirm": "short",
                "income_day": 1,
            })
            assert form.validate() is False
            assert "password" in form.errors

    def test_password_mismatch(self, req_app):
        """Password confirmation must match password."""
        with req_app.test_request_context():
            form = RegistrationForm(data={
                "username": "validuser",
                "email": "v@b.com",
                "password": "12345678",
                "password_confirm": "87654321",
                "income_day": 1,
            })
            assert form.validate() is False
            assert "password_confirm" in form.errors

    def test_income_day_below_range(self, req_app):
        """income_day must be >= 1."""
        with req_app.test_request_context():
            form = RegistrationForm(data={
                "username": "validuser",
                "email": "v@b.com",
                "password": "12345678",
                "password_confirm": "12345678",
                "income_day": 0,
            })
            assert form.validate() is False
            assert "income_day" in form.errors

    def test_income_day_above_range(self, req_app):
        """income_day must be <= 31."""
        with req_app.test_request_context():
            form = RegistrationForm(data={
                "username": "validuser",
                "email": "v@b.com",
                "password": "12345678",
                "password_confirm": "12345678",
                "income_day": 32,
            })
            assert form.validate() is False
            assert "income_day" in form.errors
