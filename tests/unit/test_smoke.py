"""Smoke test to verify test infrastructure is working."""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st


@pytest.mark.smoke
def test_pytest_runs():
    """Verify basic pytest execution works."""
    assert True


@pytest.mark.smoke
def test_hypothesis_profile_loaded():
    """Verify Hypothesis default profile is configured correctly."""
    profile = settings.get_profile("default")
    loaded = settings(profile)
    assert loaded.max_examples == 100
    assert loaded.deadline.total_seconds() * 1000 == 5000


@pytest.mark.property
@given(x=st.integers(), y=st.integers())
def test_hypothesis_works(x, y):
    """Verify Hypothesis is properly configured and runs."""
    assert x + y == y + x


@pytest.mark.smoke
@pytest.mark.integration
def test_app_fixture(app):
    """Verify Flask app fixture creates a testing app."""
    assert app.config["TESTING"] is True
    assert app.config["WTF_CSRF_ENABLED"] is False


@pytest.mark.smoke
@pytest.mark.integration
def test_client_fixture(client):
    """Verify Flask test client is available."""
    assert client is not None
