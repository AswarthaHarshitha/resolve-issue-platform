# Resolve

Intelligent Issue Resolution Platform.

## Problem

Organizations receive many complaints and service requests. Manual triage often means requests are miscategorized, assigned to the wrong team, forgotten, duplicated, or resolved slowly — and the person who submitted the request has no visibility into what happens to it next.

## Solution

Resolve centralizes issue intake. Users submit issues; an AI classification step suggests a category, sub-category, priority, summary, and reasoning; a deterministic backend rules engine (never the AI directly) decides the final category, team, priority, and SLA; resolvers work the issue through a controlled status lifecycle; and the original submitter tracks progress and confirms resolution before an issue is closed.

The core architectural principle: **AI suggests, the backend decides.** See [DECISIONS.md](DECISIONS.md) for the full reasoning, and [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) for current project status.

## Architecture

- **Frontend**: React + TypeScript + Vite + Tailwind CSS, talking to the backend over a JSON REST API.
- **Backend**: FastAPI (Python), layered as `api / core / models / schemas / services / repositories / db`, backed by PostgreSQL via SQLAlchemy.
- **AI**: an OpenAI-compatible LLM called through a small `AIProvider` interface. AI output is a validated *suggestion* only; a separate deterministic `RoutingService` makes all authorization, routing, priority, and SLA decisions. See DECISIONS.md D4–D6 for the exact boundary.
- **Async AI processing**: issue creation commits to PostgreSQL and returns immediately; AI classification runs afterward as a FastAPI background task with its own database session (DECISIONS.md D1, D3, D4, D14).

Full status lifecycle, AI-analysis lifecycle, SLA pause/resume, and status-transition rules are documented in PROJECT_CONTEXT.md and DECISIONS.md — this README will link out to specific endpoints as they're implemented rather than duplicate that detail.

## Tech stack

Frontend: React, TypeScript, Vite, Tailwind CSS.
Backend: Python, FastAPI, Pydantic, SQLAlchemy, Alembic.
Database: PostgreSQL.
Auth: JWT, password hashing, server-enforced role-based authorization.
Infra: Docker, docker-compose (local development).
Testing: pytest (backend).

## Project layout

```
resolve/
  backend/
    app/
      main.py
      api/            # route handlers
      core/            # config, security
      models/          # SQLAlchemy models
      schemas/          # Pydantic schemas
      services/         # AIProvider, RoutingService, business logic
      repositories/      # data access
      db/               # session/engine setup, migrations
    tests/
  frontend/
    src/
      components/
      pages/
      layouts/
      services/
      hooks/
      types/
      utils/
  docker-compose.yml
  PROJECT_CONTEXT.md
  DECISIONS.md
```

## Environment variables

Copy the example files and fill in real values before running anything:

```bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
```

See `backend/.env.example` and `frontend/.env.example` for the full list (database connection, JWT secret, CORS origins, AI provider key). Never commit `.env` files — only `.env.example`.

## Running locally

### With Docker (recommended)

```bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
docker compose up --build
```

- Backend: http://localhost:8000 (health check at `/health`)
- Frontend: http://localhost:5173
- PostgreSQL: localhost:5433 on the host (mapped from the container's 5432 to avoid clashing with any other local Postgres; user/db `resolve`)

### Without Docker

Backend:

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # edit DATABASE_URL to point at a local Postgres instance
uvicorn app.main:app --reload
```

Frontend:

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

## Testing

```bash
cd backend
source .venv/bin/activate
pytest
```

## Current status

Phase 1 (project setup) is complete: backend and frontend scaffolds boot and talk to each other via a `/health` check. No database models, authentication, issue workflow, or AI integration exist yet — see PROJECT_CONTEXT.md's "Pending tasks" for what's next. Sections below will be filled in as those phases land; this README does not claim functionality that doesn't exist yet.

## AI architecture

Documented in full in DECISIONS.md (D4–D6, D10, D13). Summary: the `AIProvider` service is a thin wrapper around an OpenAI-compatible chat completions API that returns a validated structured suggestion (category, sub_category, suggested_priority, summary, reasoning) — nothing more. It has no authority over authorization, routing, priority, or SLA. Implementation lands in Phase 7.

## Security considerations

To be documented as authentication (Phase 3) and the security/testing pass (Phase 9) are implemented. Design commitments already made: passwords are hashed, JWTs are used for auth, every authorization rule is enforced server-side regardless of what the frontend shows, AI output is never trusted without validation, and no secrets are committed to source control.

## Limitations

- No application functionality beyond a health check exists yet (Phase 1 of 11).
- FastAPI `BackgroundTasks` has no persistence — a server crash mid-AI-analysis can leave an issue stuck showing `PROCESSING` until a resolver/admin manually retriggers analysis. See DECISIONS.md D14.
- Single-tenant design; no multi-organization support.
- No email/push notifications in MVP — status changes are visible in-app only.

## Future improvements

- Duplicate/related-issue detection (Phase 10), suggestion-only, no auto-merge.
- Durable AI task queue (Celery/Redis or similar) if AI load or retry guarantees demand it — see DECISIONS.md D1.
- Email/push notifications.
