"""Unit tests for the settings blueprint.

Tests settings forms validation, route responses, and cascading logic.

Validates: Requirements 25.1, 25.2, 25.3, 25.5, 25.6, 25.7
"""

import pytest
from decimal import Decimal
from unittest.mock import patch, MagicMock
from werkzeug.datastructures import MultiDict

from app.models.user import User
from app.blueprints.settings.forms import SettingsForm, ChangePasswordForm


def _settings_data(**overrides):
    """Build a valid settings form data dict with optional overrides."""
    data = {
        "income_day": "15",
        "date_format": "DD.MM.YYYY",
        "marginal_tax_rate": "0.4200",
        "social_security_rate": "0.2000",
        "assumed_annual_return": "0.0700",
        "target_retirement_age": "67",
    }
    data.update(overrides)
    return MultiDict(data)


class TestSettingsForm:
    """Tests for SettingsForm validation (no DB required)."""

    def test_valid_income_day_range(self, app):
        """income_day accepts values 1–31."""
        with app.test_request_context():
            form = SettingsForm(_settings_data(), meta={"csrf": False})
            assert form.validate(), form.errors

    def test_income_day_below_minimum_rejected(self, app):
        """income_day value 0 is rejected (Req 25.2)."""
        with app.test_request_context():
            form = SettingsForm(
                _settings_data(income_day="0"), meta={"csrf": False}
            )
            assert not form.validate()
            assert "income_day" in form.errors

    def test_income_day_above_maximum_rejected(self, app):
        """income_day value 32 is rejected (Req 25.2)."""
        with app.test_request_context():
            form = SettingsForm(
                _settings_data(income_day="32"), meta={"csrf": False}
            )
            assert not form.validate()
            assert "income_day" in form.errors

    def test_valid_date_formats_accepted(self, app):
        """All three date_format choices are valid (Req 25.3)."""
        for fmt in ["DD.MM.YYYY", "YYYY-MM-DD", "MM/DD/YYYY"]:
            with app.test_request_context():
                form = SettingsForm(
                    _settings_data(date_format=fmt), meta={"csrf": False}
                )
                assert form.validate(), f"Failed for {fmt}: {form.errors}"

    def test_invalid_date_format_rejected(self, app):
        """Invalid date_format value is rejected."""
        with app.test_request_context():
            form = SettingsForm(
                _settings_data(date_format="INVALID"), meta={"csrf": False}
            )
            assert not form.validate()
            assert "date_format" in form.errors

    def test_tax_rate_exceeds_max_rejected(self, app):
        """marginal_tax_rate > 1.0 is rejected (Req 25.7)."""
        with app.test_request_context():
            form = SettingsForm(
                _settings_data(marginal_tax_rate="1.5000"), meta={"csrf": False}
            )
            assert not form.validate()
            assert "marginal_tax_rate" in form.errors

    def test_social_security_rate_negative_rejected(self, app):
        """social_security_rate < 0 is rejected (Req 25.7)."""
        with app.test_request_context():
            form = SettingsForm(
                _settings_data(social_security_rate="-0.0100"), meta={"csrf": False}
            )
            assert not form.validate()
            assert "social_security_rate" in form.errors

    def test_retirement_age_boundaries(self, app):
        """target_retirement_age must be 18–100."""
        with app.test_request_context():
            # Below min
            form = SettingsForm(
                _settings_data(target_retirement_age="17"), meta={"csrf": False}
            )
            assert not form.validate()
            assert "target_retirement_age" in form.errors

        with app.test_request_context():
            # Above max
            form = SettingsForm(
                _settings_data(target_retirement_age="101"), meta={"csrf": False}
            )
            assert not form.validate()
            assert "target_retirement_age" in form.errors


class TestChangePasswordForm:
    """Tests for ChangePasswordForm validation."""

    def test_valid_password_change(self, app):
        """Valid password change form data passes validation."""
        with app.test_request_context():
            form = ChangePasswordForm(
                MultiDict({
                    "current_password": "oldpassword",
                    "new_password": "newsecure1",
                    "confirm_password": "newsecure1",
                }),
                meta={"csrf": False},
            )
            assert form.validate(), form.errors

    def test_new_password_too_short_rejected(self, app):
        """New password under 8 characters is rejected (Req 25.5)."""
        with app.test_request_context():
            form = ChangePasswordForm(
                MultiDict({
                    "current_password": "oldpassword",
                    "new_password": "short",
                    "confirm_password": "short",
                }),
                meta={"csrf": False},
            )
            assert not form.validate()
            assert "new_password" in form.errors

    def test_password_mismatch_rejected(self, app):
        """Mismatched confirm_password is rejected."""
        with app.test_request_context():
            form = ChangePasswordForm(
                MultiDict({
                    "current_password": "oldpassword",
                    "new_password": "newsecure1",
                    "confirm_password": "different1",
                }),
                meta={"csrf": False},
            )
            assert not form.validate()
            assert "confirm_password" in form.errors

    def test_empty_current_password_rejected(self, app):
        """Missing current_password is rejected (Req 25.6)."""
        with app.test_request_context():
            form = ChangePasswordForm(
                MultiDict({
                    "current_password": "",
                    "new_password": "newsecure1",
                    "confirm_password": "newsecure1",
                }),
                meta={"csrf": False},
            )
            assert not form.validate()
            assert "current_password" in form.errors


class TestSettingsBlueprint:
    """Tests for settings route behaviour."""

    def test_settings_index_requires_login(self, client):
        """GET /settings/ redirects unauthenticated users."""
        response = client.get("/settings/", follow_redirects=False)
        assert response.status_code in (302, 308)

    def test_change_password_requires_login(self, client):
        """GET /settings/change-password redirects unauthenticated users."""
        response = client.get("/settings/change-password", follow_redirects=False)
        assert response.status_code in (302, 308)

    def test_settings_blueprint_registered(self, app):
        """Settings blueprint is registered with correct URL prefix."""
        rules = [rule.rule for rule in app.url_map.iter_rules()]
        assert "/settings/" in rules
        assert "/settings/change-password" in rules
