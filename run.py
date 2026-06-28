"""Entry point for the Haushaltsbuch Flask application.

Usage:
    python run.py

Or with Flask CLI:
    flask run
"""

import os

from app import create_app

config_name = os.environ.get("FLASK_ENV", "development")
app = create_app(config_name)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
