# Kirkos-LCPPME — Plan, KPI, Performance & Monitoring System

A Flask application for annual plans, work processes, teams, KPIs, performance tracking, findings, corrective actions and summary reports. Interface labels are primarily in Amharic.

## Important persistence note
- Local development uses SQLite by default.
- Production should use PostgreSQL through `DATABASE_URL`.
- Render free PostgreSQL services have service-specific expiry/retention limitations. Check Render's current pricing and retention terms before relying on a free database for official records. For institutional production, use a supported paid database or another managed PostgreSQL provider and schedule backups.
- Never commit `.env`, database passwords, or secret keys.

## Features
- Login/logout and roles (Admin, Manager, Staff)
- Dashboard totals and recent plans
- Annual plan registration with date validation, process/team validation, listing and admin-only deletion
- Work process and team setup
- KPI registration
- Performance progress reporting
- Findings and corrective action tracking
- Summary reports
- Health check at `/health`

## Deploy on Render
1. Create a new GitHub repository and upload the contents of this project (the files inside the ZIP, not the ZIP itself).
2. In Render, create a PostgreSQL database. Copy its **Internal Database URL** only into the web service environment variable `DATABASE_URL` when the database and service are in the same Render region.
3. Create a Web Service from the repository.
4. Build command: `pip install -r requirements.txt`
5. Start command: `gunicorn --workers 1 --threads 4 --timeout 120 app:app`
6. Add environment variables:
   - `SECRET_KEY`: a long random secret
   - `DATABASE_URL`: managed PostgreSQL connection string
   - `ADMIN_USERNAME`: e.g. `systemadmin`
   - `ADMIN_PASSWORD`: a unique strong password (at least 10 characters)
7. Open `/health` and confirm it returns `{"status":"ok","database":"connected"}`.
8. Sign in using the configured admin username/password.

### Render Blueprint note
`render.yaml` is a convenience starting point. Confirm current Render plan availability and database pricing before applying it. If the selected database plan is unavailable for your account/region, create the database manually and set `DATABASE_URL` in the web service.

## Run locally
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```
Set `ADMIN_USERNAME`, `ADMIN_PASSWORD`, and `SECRET_KEY` in the environment before starting the app. Then:
```bash
python app.py
```
Open `http://127.0.0.1:5000`.

## Security and operational notes
- Admin account is created only if `ADMIN_PASSWORD` is configured and the account does not already exist.
- Do not use a publicly known/default admin password.
- The app uses `db.create_all()` for initial schema creation. For future production schema changes, introduce Alembic/Flask-Migrate migrations and back up the database before migration.
- Keep backups and test restore procedures regularly.
- This starter implementation should undergo institutional security review before being used with real taxpayer or other confidential records.
