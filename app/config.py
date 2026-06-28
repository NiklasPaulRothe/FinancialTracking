"""Configuration classes for Haushaltsbuch application.

Environment variables are loaded from a .env file in the project root
via python-dotenv (see run.py or flask CLI auto-discovery).
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root
_basedir = Path(__file__).resolve().parent.parent
load_dotenv(_basedir / ".env")


class Config:
    """Base configuration shared across all environments."""

    SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-in-production")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Flask-WTF
    WTF_CSRF_ENABLED = True

    # APScheduler
    SCHEDULER_API_ENABLED = False
    SCHEDULER_EXECUTORS = {"default": {"type": "threadpool", "max_workers": 1}}
    SCHEDULER_JOB_DEFAULTS = {"coalesce": "true", "max_instances": "1"}


class DevelopmentConfig(Config):
    """Development configuration with debug enabled."""

    DEBUG = True
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/haushaltsbuch",
    )
    SCHEDULER_JOBSTORES = {
        "default": {
            "type": "sqlalchemy",
            "url": os.environ.get(
                "DATABASE_URL",
                "postgresql://postgres:postgres@localhost:5432/haushaltsbuch",
            ),
        }
    }


class TestingConfig(Config):
    """Testing configuration with separate database and CSRF disabled."""

    TESTING = True
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/haushaltsbuch_test",
    )
    WTF_CSRF_ENABLED = False
    SCHEDULER_API_ENABLED = False
    # Use in-memory job store for tests
    SCHEDULER_JOBSTORES = {"default": {"type": "memory"}}
    SCHEDULER_EXECUTORS = {"default": {"type": "threadpool", "max_workers": 1}}


class ProductionConfig(Config):
    """Production configuration with secure defaults."""

    DEBUG = False
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL")
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PREFERRED_URL_SCHEME = "https"
    SCHEDULER_JOBSTORES = {
        "default": {
            "type": "sqlalchemy",
            "url": os.environ.get("DATABASE_URL"),
        }
    }


config_by_name = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}
