"""Shared test fixtures and Hypothesis configuration for Haushaltsbuch."""

import pytest
from hypothesis import settings, HealthCheck

from app import create_app
from app.extensions import db as _db


# ---------------------------------------------------------------------------
# Hypothesis profile configuration
# ---------------------------------------------------------------------------
settings.register_profile(
    "default",
    max_examples=100,
    deadline=5000,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.register_profile(
    "ci",
    max_examples=200,
    deadline=10000,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile("default")


# ---------------------------------------------------------------------------
# Application fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def app():
    """Create Flask application configured for testing.

    Scope is session-wide so we only create the app once per test run.
    """
    application = create_app("testing")

    # Establish application context for the full session
    with application.app_context():
        yield application


@pytest.fixture(scope="session")
def _setup_db(app):
    """Create all database tables once per session, drop on teardown."""
    _db.create_all()
    yield _db
    _db.drop_all()


@pytest.fixture()
def db_session(app, _setup_db):
    """Provide a transactional database session that rolls back after each test.

    Uses nested transactions (SAVEPOINTs) so each test sees an isolated state:
    1. Begin an outer transaction on the connection.
    2. Bind the session to that connection.
    3. After the test, roll back the outer transaction — any changes are discarded.
    """
    connection = _setup_db.engine.connect()
    transaction = connection.begin()

    # Bind the scoped session to this connection
    _setup_db.session.configure(bind=connection)

    # Use a nested transaction (SAVEPOINT) so that application code calling
    # session.commit() doesn't actually commit the outer transaction.
    nested = connection.begin_nested()

    # Listen for session commit events to restart the SAVEPOINT
    @_db.event.listens_for(_setup_db.session, "after_transaction_end")
    def restart_savepoint(session, trans):
        nonlocal nested
        if trans.nested and not trans._parent.nested:
            nested = connection.begin_nested()
            session.configure(bind=connection)

    yield _setup_db.session

    # Cleanup: rollback and close
    _setup_db.session.remove()
    transaction.rollback()
    connection.close()


@pytest.fixture()
def client(app):
    """Flask test client for making HTTP requests."""
    return app.test_client()


@pytest.fixture()
def runner(app):
    """Flask CLI test runner."""
    return app.test_cli_runner()
