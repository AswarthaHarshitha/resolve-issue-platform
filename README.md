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
      db/               # session/engine setup, base/mixins
    alembic/            # migrations (source of truth for schema - see below)
    tests/
  frontend/
    src/
      components/     # ProtectedRoute, etc.
      context/         # AuthContext (session state)
      pages/           # LoginPage, RegisterPage, HomePage
      layouts/
      services/        # api.ts (fetch client), authApi.ts, tokenStorage.ts
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

## Database setup

Schema is managed entirely through Alembic migrations — the app never relies on `Base.metadata.create_all()` against a real database (see DECISIONS.md D1's neighbors, D15–D19, for the schema itself). After the database is up and `backend/.env` points at it:

```bash
cd backend
source .venv/bin/activate   # or run this inside the backend container
alembic upgrade head
```

This creates all 13 tables, their constraints/indexes, and seeds the three baseline roles (`USER`/`RESOLVER`/`ADMIN` — required reference data, not demo content; see DECISIONS.md D16). `alembic downgrade base` fully reverses it. Point `DATABASE_URL` at a fresh database and re-run `alembic upgrade head` any time you need a clean schema.

## Running locally

### With Docker (recommended)

```bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
docker compose up --build -d db backend frontend
docker compose exec backend alembic upgrade head
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
alembic upgrade head
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

The test suite needs a reachable PostgreSQL server (the same one `DATABASE_URL` points at, or a separate `TEST_DATABASE_URL`) — it creates a dedicated `resolve_test` database on first run and applies every Alembic migration to it directly, so tests exercise the real migration path rather than a `create_all()` shortcut. It never touches the dev/prod database.

## Authentication

`POST /api/v1/auth/register` (always creates a `USER` account — no client-supplied role is ever honored), `POST /api/v1/auth/login` (returns a JWT), `GET /api/v1/auth/me` (requires a valid token), `POST /api/v1/auth/logout` (stateless — see below). Passwords are hashed with bcrypt (DECISIONS.md D26). JWTs carry only `sub`/`iat`/`exp` — never a role claim — and every protected request reloads the current user (role, `is_active`) fresh from PostgreSQL, so a permission change or account deactivation takes effect immediately rather than waiting for a token to expire (DECISIONS.md D21).

**Logout** is a client-side action: the frontend discards its token, but the token itself remains valid (stateless JWTs, no server-side revocation) until it naturally expires — an explicit, documented MVP tradeoff, not a hidden gap (DECISIONS.md D22).

**RBAC**: reusable FastAPI dependencies (`require_role`, `require_any_role` in `app/core/deps.py`) enforce `USER`/`RESOLVER`/`ADMIN` access server-side on every protected endpoint — role checks are exact-match, never hierarchical. The frontend's route guarding is a UX convenience only; it has no bearing on what the backend actually allows.

**Token storage**: the frontend keeps the JWT in `localStorage` and sends it via `Authorization: Bearer`. This is not XSS-resistant — see DECISIONS.md D27 for the full tradeoff and what a hardened production deployment would do instead (httpOnly cookies + CSRF protection).

**Rate limiting**: `/auth/login` and `/auth/register` are protected by a lightweight in-memory, single-process limiter (10 attempts/60s by default) — explicitly not a distributed rate limiter; see DECISIONS.md D25.

## Issue lifecycle

`POST /api/v1/issues` (any authenticated user), `GET /api/v1/issues` (paginated, filterable — a USER sees only their own, RESOLVER/ADMIN see all), `GET /api/v1/issues/{id}`, `PATCH /api/v1/issues/{id}/status` (RESOLVER/ADMIN only). Status transitions are validated server-side against a fixed allow-list (`OPEN → TRIAGED → ASSIGNED → IN_PROGRESS ⇄ WAITING_FOR_USER → RESOLVED`) using a `SELECT ... FOR UPDATE` row lock, so a concurrent transition request is always evaluated against the real current state, never a stale or client-supplied one — verified with a genuine multi-threaded test, not just asserted. `RESOLVED → CLOSED` is intentionally unreachable through this endpoint; it's reserved for Phase 7's dedicated user-confirmation flow. See PROJECT_CONTEXT.md's ISSUE LIFECYCLE section and DECISIONS.md D29–D32.

## AI analysis & routing

`POST /issues` returns immediately (issue committed as OPEN/PENDING); AI classification runs afterward as a `BackgroundTask`, in its own DB session. `AIProvider` (`app/services/ai_provider.py`) is a thin, swappable wrapper around any OpenAI-compatible chat completions endpoint — configure `OPENAI_BASE_URL` to point at a different provider (verified working against Google's Gemini OpenAI-compatibility layer). Its output is validated in two layers: structural (right JSON shape) in the provider itself, semantic (does this category/priority actually exist in this deployment's configuration) in `ai_validation.py` — a mismatch is a hard failure, never a fabricated match. `RoutingService` then makes every actual decision (final priority via deterministic keyword escalation, team via `routing_rules`, SLA via `sla_rules`) — the AI's suggestion is advisory input to that decision, never the decision itself; `AISuggestion` has no field capable of setting a team, role, or SLA even in principle. Manual recovery: `POST /issues/{id}/reanalyze` (resolver/admin only, cooldown-limited), which only re-routes an issue still `OPEN` — on an already-progressed issue it just records a fresh opinion without touching what a human may already be acting on. See PROJECT_CONTEXT.md's AI ANALYSIS & ROUTING section and DECISIONS.md D33–D39.

## SLA engine

Pause/resume is wired directly into the status-transition endpoint: entering `WAITING_FOR_USER` opens an `sla_pause_intervals` row, leaving it closes one and folds the duration into a maintained cache column — both inside the same transaction as the status change, so they can never drift apart. `sla_service.compute_sla_status()` is a pure function over persisted rows only (no in-memory state, verified by discarding and reloading a record mid-test and confirming an identical result) that returns effective elapsed time and at-risk/breached flags for both the first-response and resolution targets independently, using a fixed, configurable at-risk threshold (20% of the original duration remaining, by default). Every issue response includes the computed result under `sla`. See PROJECT_CONTEXT.md's SLA ENGINE section and DECISIONS.md D40.

## Current status

Phase 6 (SLA engine) is complete, on top of Phases 2–5. 157 passing pytest tests (40 database + 47 auth/RBAC + 28 issue domain + 27 AI/routing + 15 SLA, including a restart-simulation test and a real two-connection concurrency test for simultaneous `WAITING_FOR_USER` entry) — plus a live end-to-end verification: a real ~18-second wait was correctly excluded from the reported elapsed time after resuming. See PROJECT_CONTEXT.md's SLA ENGINE section for the full flow and DECISIONS.md D40 for the design reasoning. No comments, assignment history, or resolver-workflow endpoints exist yet — see PROJECT_CONTEXT.md's "Pending tasks." This README does not claim functionality that doesn't exist yet.

## Security considerations

Implemented so far (Phases 3–6): passwords hashed with bcrypt, never stored or returned in plaintext; JWT signature and expiration always verified server-side; role/active-state always read fresh from the database, never trusted from the token; public registration structurally cannot create an elevated-privilege account; login responses don't reveal whether an email is registered; CORS restricted to an explicit origin allow-list; lightweight rate limiting on auth endpoints; unhandled exceptions (including database failures) never leak internals to the client; issue access is authorization-checked server-side (owner or staff role) regardless of what a client requests; status transitions (including the SLA pause/resume they trigger) are validated against a locked, real-time database read, never trusted client state; AI output is never trusted without validation, and has no field capable of an authorization/routing/SLA decision even structurally. Full attack-review findings are in DECISIONS.md D20–D40. Still to come: the broader Phase 9 security/failure attack pass once resolver-workflow functionality exists to attack.

## Limitations

- No comments, assignment history, or resolver-workflow endpoints exist yet (Phase 6 of 11 complete).
- No admin-facing way to provision RESOLVER/ADMIN accounts yet — those roles can currently only be assigned by writing directly to the database. A controlled provisioning flow is a later-phase concern (DECISIONS.md D23).
- No admin-facing way to populate categories/teams/routing/SLA rules yet — `backend/scripts/seed_dev_reference_data.py` is an explicit, dev-only convenience until Phase 8 adds a real management UI (DECISIONS.md D39).
- Issue authorization is coarse-grained (owner vs. any staff), not team-scoped yet — DECISIONS.md D29. Team-scoped resolver access lands in Phase 7.
- The SLA "at risk" threshold (20% of duration remaining) is a fixed, documented heuristic, not a per-category/priority configurable rule — reasonable for MVP, would be a natural refinement later.
- Logout does not invalidate the token server-side (stateless JWT tradeoff, DECISIONS.md D22) — a "logged out" token remains usable until it naturally expires (60 minutes by default).
- Auth rate limiting is in-memory and single-process — it does not protect a horizontally-scaled, multi-instance deployment (DECISIONS.md D25).
- The manual-reanalysis cooldown is likewise in-memory-adjacent (stored per-issue via `ai_analysis_results` timestamps in the database, so it *is* durable and shared across processes — unlike the auth rate limiter, this one is not a known gap).
- FastAPI `BackgroundTasks` has no persistence — a process restart mid-analysis can leave an issue stuck at `ai_analysis_status=PROCESSING`; manual reanalysis is the recovery path (DECISIONS.md D14).
- Frontend token storage (`localStorage`) is not XSS-resistant (DECISIONS.md D27).
- FastAPI `BackgroundTasks` has no persistence — a server crash mid-AI-analysis can leave an issue stuck showing `PROCESSING` until a resolver/admin manually retriggers analysis. See DECISIONS.md D14.
- Single-tenant design; no multi-organization support.
- No email/push notifications in MVP — status changes are visible in-app only.

## Future improvements

- Duplicate/related-issue detection (Phase 10), suggestion-only, no auto-merge.
- Durable AI task queue (Celery/Redis or similar) if AI load or retry guarantees demand it — see DECISIONS.md D1.
- Email/push notifications.
