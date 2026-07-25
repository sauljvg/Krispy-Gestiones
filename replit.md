# Krispy Track

Analytics dashboard for Google Maps reviews of Krispy Kreme stores in Colombia.

## Stack

- **Backend**: FastAPI + SQLite (`krispy_kreme.db`)
- **Frontend**: Static HTML/CSS/JS served by FastAPI at `/`
- **Scraper**: Selenium + Chrome (runs locally only — Replit cannot run Chrome)

## How to run

The app is configured to start automatically via the **"Start application"** workflow:

```bash
python -m uvicorn backend.main:app --host 0.0.0.0 --port 5000
```

This serves both the API (`/api/*`) and the frontend dashboard at the same port.

## Project structure

```
backend/        FastAPI app, routes, analytics, DB connection
frontend/       Static HTML + CSS + JS dashboard
scraper/        Selenium scraper (local use only)
common.py       Shared date parsing + sentiment logic
krispy_kreme.db SQLite database with scraped reviews
requirements.txt
```

## Updating data

The scraper runs locally (requires Chrome). To refresh data on Replit, run the scraper locally and commit/upload the updated `krispy_kreme.db`.

A nightly scheduler inside the app also triggers incremental updates at 02:00 via `POST /api/scrape` (update mode), but this only works if you have a working scraper environment.

## Data persistence (Autoscale)

`krispy_kreme.db` and the `uploads/`/`backups/` folders live on Autoscale's
ephemeral disk, which is wiped on every redeploy. Two safety nets keep data
across redeploys:

- A backup runs every 6h and again right when the container gets the
  shutdown signal (`backend/main.py`'s `shutdown` event), uploaded to
  Replit Object Storage (`backend/storage_sync.py`).
- On boot, if the local DB is missing or suspiciously small, the latest
  backup is restored automatically before anything else runs.

Check `GET /api/admin/backup-status` (admin session required) to confirm
Object Storage is reachable and see the most recent remote backup.

`DATA_DIR` (env var) lets all of this point at a real persistent volume
instead — used when deploying to Fly.io, unset here so Replit keeps its
current behavior.

## User preferences
