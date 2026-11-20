# 🐛 Bug Tracker (FastAPI + React + Tailwind)
Jira-like tracker: JWT auth, projects, roles (admin/developer/viewer), tickets, drag-and-drop Kanban, threaded comments, filters + search, screenshot uploads. Swagger docs at `/docs`.

## Run locally
    pip install -r requirements.txt
    uvicorn main:app --reload      # open http://localhost:8000

## Deploy (one service serves API + UI)
Env vars: `SECRET_KEY` (random string), `DATABASE_URL` (Postgres URL; defaults to SQLite).
- **Railway / Render**: push to GitHub → New Project from repo → add Postgres → set the env vars. The Procfile starts the app.
- **Fly.io**: `fly launch` (uses the Dockerfile), `fly secrets set SECRET_KEY=... DATABASE_URL=...`, `fly deploy`.
Note: uploaded screenshots live on local disk; attach a volume (or swap in S3) for persistence.

## Roles
admin: everything + manage members + delete any ticket · developer: create/edit/comment/upload, delete own tickets · viewer: read-only.
