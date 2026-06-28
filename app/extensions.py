"""Flask extension instances for Haushaltsbuch.

Extensions are instantiated here without an app reference and initialized
in the application factory via init_app().
"""

from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_apscheduler import APScheduler

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
scheduler = APScheduler()

# Configure Flask-Login defaults
login_manager.login_view = "auth.login"
login_manager.login_message = "Bitte melden Sie sich an, um auf diese Seite zuzugreifen."
login_manager.login_message_category = "warning"
