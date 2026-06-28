"""Alembic environment configuration for Flask-Migrate.

This file is executed by Alembic every time a migration command runs.
Flask-Migrate injects the Flask app's SQLAlchemy engine and metadata
so that autogenerate can detect model changes.
"""

import logging
from logging.config import fileConfig

from flask import current_app

from alembic import context

# Ensure all models are imported so their tables are registered on
# db.metadata before autogenerate compares against the database.
import app.models  # noqa: F401

# Alembic Config object – provides access to alembic.ini values
config = context.config

# Set up Python logging from the config file
fileConfig(config.config_file_name)
logger = logging.getLogger("alembic.env")


def get_engine():
    """Return the SQLAlchemy engine from the Flask app."""
    try:
        # Flask-SQLAlchemy >= 3
        return current_app.extensions["migrate"].db.get_engine()
    except (TypeError, AttributeError):
        # Older versions
        return current_app.extensions["migrate"].db.engine


def get_engine_url():
    """Return the database URL as a string for offline mode."""
    try:
        return get_engine().url.render_as_string(hide_password=False).replace("%", "%%")
    except AttributeError:
        return str(get_engine().url).replace("%", "%%")


# Target metadata for autogenerate support – pulled from Flask-Migrate's
# reference to db.metadata which includes all registered models.
config.set_main_option("sqlalchemy.url", get_engine_url())
target_db = current_app.extensions["migrate"].db


def get_metadata():
    """Return the metadata object used for autogenerate comparison."""
    if hasattr(target_db, "metadatas"):
        return target_db.metadatas[None]
    return target_db.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL and not an Engine.
    Calls to context.execute() emit the given string to the script output.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=get_metadata(),
        literal_binds=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we create an Engine and associate a connection
    with the context.
    """

    # This callback prevents an auto-migration from being generated
    # when there are no changes to the schema.
    def process_revision_directives(context, revision, directives):
        if getattr(config.cmd_opts, "autogenerate", False):
            script = directives[0]
            if script.upgrade_ops.is_empty():
                directives[:] = []
                logger.info("No changes in schema detected.")

    connectable = get_engine()

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=get_metadata(),
            process_revision_directives=process_revision_directives,
            **current_app.extensions["migrate"].configure_args,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
