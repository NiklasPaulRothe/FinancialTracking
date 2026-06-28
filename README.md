# Haushaltsbuch — Personal & Shared Finance Tracker

A Flask-based household finance management application for two users.

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Create the database schema

Assuming the `haushaltsbuch` database already exists on your PostgreSQL server:

```bash
psql -U postgres -d haushaltsbuch -f sql/create_database.sql
```

### 3. Configure environment

```bash
copy .env.example .env
```

Edit `.env` and set your postgres password:

```
DATABASE_URL=postgresql://postgres:your_password@localhost:5432/haushaltsbuch
SECRET_KEY=some-random-secret-string
```

### 4. Run the application

```bash
python run.py
```

The app will be available at `http://localhost:5000`.

## Project Structure

- `app/` — Flask application (blueprints, models, services, templates)
- `sql/` — Database creation scripts
- `tests/` — Test suite (unit, integration, property)
- `migrations/` — Alembic database migrations
- `.env.example` — Environment variable template