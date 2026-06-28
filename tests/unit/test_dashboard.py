"""Unit tests for dashboard blueprint.

Tests the view toggle logic, session storage, and route behaviour
for the personal/shared dashboard views.

Validates: Requirements 23.1, 23.2, 23.3, 23.4, 23.5
"""

import pytest
from unittest.mock import patch, MagicMock
from decimal import Decimal
from datetime import date

from app.models.user import User


@pytest.fixture()
def logged_in_client(app, db_session):
    """Create a logged-in test client with a real user in the database."""
    from werkzeug.security import generate_password_hash

    user = User(
        username="dashuser",
        email="dashuser@example.com",
        password_hash=generate_password_hash("testpass123"),
        income_day=25,
        date_format="DD.MM.YYYY",
        marginal_tax_rate=Decimal("0.4200"),
        social_security_rate=Decimal("0.2050"),
        assumed_annual_return=Decimal("0.0700"),
        target_retirement_age=67,
    )
    db_session.add(user)
    db_session.flush()

    client = app.test_client()
    # Log in via Flask-Login test utilities
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)

    return client, user


class TestDashboardViewToggle:
    """Test personal/shared view toggle stored in session."""

    def test_default_view_is_personal(self, logged_in_client):
        """Dashboard defaults to personal view when no session is set."""
        client, _ = logged_in_client
        response = client.get("/")
        assert response.status_code == 200
        assert "Persönlich".encode("utf-8") in response.data

    def test_toggle_to_shared_view(self, logged_in_client):
        """Passing ?view=shared stores preference and redirects."""
        client, _ = logged_in_client
        response = client.get("/?view=shared")
        # Should redirect to index without query param
        assert response.status_code == 302

        # Follow redirect
        response = client.get("/", follow_redirects=True)
        assert response.status_code == 200
        assert "Gemeinsam".encode("utf-8") in response.data

    def test_toggle_to_personal_view(self, logged_in_client):
        """Passing ?view=personal stores preference and redirects."""
        client, _ = logged_in_client
        # First set to shared
        client.get("/?view=shared")
        # Then toggle back to personal
        response = client.get("/?view=personal")
        assert response.status_code == 302

        response = client.get("/", follow_redirects=True)
        assert response.status_code == 200

    def test_invalid_view_param_ignored(self, logged_in_client):
        """Invalid view parameter does not change session state."""
        client, _ = logged_in_client
        response = client.get("/?view=invalid")
        # Should render normally (not redirect) since invalid view is ignored
        assert response.status_code == 200

    def test_session_persists_view_preference(self, logged_in_client):
        """View preference persists across multiple requests."""
        client, _ = logged_in_client
        # Set to shared
        client.get("/?view=shared", follow_redirects=True)

        # Subsequent request without param should stay in shared
        response = client.get("/")
        assert response.status_code == 200
        assert "Gemeinsamer Kontostand".encode("utf-8") in response.data


class TestDashboardPersonalView:
    """Test personal view displays correct data sections."""

    def test_personal_view_renders_balance_card(self, logged_in_client):
        """Personal view shows the total/available balance card."""
        client, _ = logged_in_client
        response = client.get("/")
        assert response.status_code == 200
        assert "Kontostand".encode("utf-8") in response.data
        assert "Gesamtsaldo".encode("utf-8") in response.data
        assert "Verfügbar".encode("utf-8") in response.data

    def test_personal_view_renders_income_cycle(self, logged_in_client):
        """Personal view shows income cycle progress section."""
        client, _ = logged_in_client
        response = client.get("/")
        assert response.status_code == 200
        assert "Einkommenszyklus".encode("utf-8") in response.data

    def test_personal_view_renders_empty_budgets(self, logged_in_client):
        """Personal view shows empty state for budgets with create link."""
        client, _ = logged_in_client
        response = client.get("/")
        assert response.status_code == 200
        assert "Budgets".encode("utf-8") in response.data
        assert "Keine Budgets vorhanden".encode("utf-8") in response.data
        assert "Budget erstellen".encode("utf-8") in response.data

    def test_personal_view_renders_empty_recurring(self, logged_in_client):
        """Personal view shows empty state for recurring with create link."""
        client, _ = logged_in_client
        response = client.get("/")
        assert response.status_code == 200
        assert "Nächste Ausgaben".encode("utf-8") in response.data
        assert "Dauerauftrag erstellen".encode("utf-8") in response.data

    def test_personal_view_renders_empty_transactions(self, logged_in_client):
        """Personal view shows empty state for transactions with create link."""
        client, _ = logged_in_client
        response = client.get("/")
        assert response.status_code == 200
        assert "Letzte Transaktionen".encode("utf-8") in response.data
        assert "Transaktion erstellen".encode("utf-8") in response.data

    def test_personal_view_renders_empty_credits(self, logged_in_client):
        """Personal view shows empty state for credits with create link."""
        client, _ = logged_in_client
        response = client.get("/")
        assert response.status_code == 200
        assert "Aktive Kredite".encode("utf-8") in response.data
        assert "Kredit erstellen".encode("utf-8") in response.data

    def test_personal_view_renders_empty_saving_goals(self, logged_in_client):
        """Personal view shows empty state for saving goals with create link."""
        client, _ = logged_in_client
        response = client.get("/")
        assert response.status_code == 200
        assert "Sparziele".encode("utf-8") in response.data
        assert "Sparziel erstellen".encode("utf-8") in response.data

    def test_personal_view_renders_planned_expenses_section(self, logged_in_client):
        """Personal view shows planned expenses count section."""
        client, _ = logged_in_client
        response = client.get("/")
        assert response.status_code == 200
        assert "Geplante Ausgaben".encode("utf-8") in response.data


class TestDashboardSharedView:
    """Test shared view displays correct data sections."""

    def test_shared_view_renders_balance(self, logged_in_client):
        """Shared view shows the shared account balance."""
        client, _ = logged_in_client
        client.get("/?view=shared", follow_redirects=True)
        response = client.get("/")
        assert response.status_code == 200
        assert "Gemeinsamer Kontostand".encode("utf-8") in response.data

    def test_shared_view_renders_settlement(self, logged_in_client):
        """Shared view shows the settlement/Ausgleich section."""
        client, _ = logged_in_client
        client.get("/?view=shared", follow_redirects=True)
        response = client.get("/")
        assert response.status_code == 200
        assert "Ausgleich".encode("utf-8") in response.data

    def test_shared_view_renders_empty_shared_budgets(self, logged_in_client):
        """Shared view shows empty state for shared budgets."""
        client, _ = logged_in_client
        client.get("/?view=shared", follow_redirects=True)
        response = client.get("/")
        assert response.status_code == 200
        assert "Gemeinsame Budgets".encode("utf-8") in response.data

    def test_shared_view_renders_empty_shared_recurring(self, logged_in_client):
        """Shared view shows empty state for shared recurring."""
        client, _ = logged_in_client
        client.get("/?view=shared", follow_redirects=True)
        response = client.get("/")
        assert response.status_code == 200
        assert "Nächste gemeinsame Ausgaben".encode("utf-8") in response.data

    def test_shared_view_renders_empty_shared_transactions(self, logged_in_client):
        """Shared view shows empty state for shared transactions."""
        client, _ = logged_in_client
        client.get("/?view=shared", follow_redirects=True)
        response = client.get("/")
        assert response.status_code == 200
        assert "Letzte gemeinsame Transaktionen".encode("utf-8") in response.data


class TestDashboardRequiresLogin:
    """Test that dashboard requires authentication."""

    def test_unauthenticated_redirects_to_login(self, client):
        """Unauthenticated users are redirected to login."""
        response = client.get("/")
        assert response.status_code == 302
        assert "/auth/login" in response.headers.get("Location", "")
