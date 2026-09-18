# Resolve

Intelligent Issue Resolution Platform.

## Live application

- **Frontend:** https://resolve-issue-platform.vercel.app
- **Backend API:** https://resolve-backend-but8.onrender.com
- **Health check:** https://resolve-backend-but8.onrender.com/health
- **API docs (Swagger UI):** https://resolve-backend-but8.onrender.com/docs

Free-tier hosting: the backend (Render free web service) spins down after periods of inactivity and takes roughly 30-60 seconds to wake up on the next request (a cold start, not a bug); the database (Supabase free project) can similarly pause after extended inactivity and resume automatically on the next connection. Neither is masked with artificial keep-alive traffic - see "Known limitations" below.

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

This creates all 15 tables, their constraints/indexes, and seeds the three baseline roles (`USER`/`RESOLVER`/`ADMIN` — required reference data, not demo content; see DECISIONS.md D16). `alembic downgrade base` fully reverses it. Point `DATABASE_URL` at a fresh database and re-run `alembic upgrade head` any time you need a clean schema.

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

A fresh database has no `RESOLVER`/`ADMIN` account (registration always creates `USER` - DECISIONS.md D23). To reach admin-only UI/API locally:

```bash
docker compose exec backend python -m scripts.bootstrap_dev_admin
```

Prints a one-time local-development-only email/password to stdout (never written to a file). Development-only - refuses to run unless `ENVIRONMENT=development` (DECISIONS.md D49). `backend/scripts/seed_dev_reference_data.py` similarly seeds categories/teams/routing/SLA reference data so there's something for issues to route to.

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

## Production deployment

### Architecture

```
                 Internet
                    │
                    ▼
         React frontend (Vercel, free)
                    │
                    │ HTTPS, VITE_API_BASE_URL
                    ▼
        FastAPI backend (Render, free web service)
                    │
          ┌─────────┴─────────┐
          ▼                   ▼
  PostgreSQL (Supabase,   AI provider (OpenAI-
  free, via connection    compatible endpoint,
  pooler)                 configured by env var)
```

Same architecture as local development - a layered monolith, no queue, no cache, no microservices. The only difference between environments is configuration (`ENVIRONMENT=production`, real secrets, the production CORS origin) - no code path branches on which environment it's running in beyond that.

### Environment variables (production)

Set as secrets in each provider's dashboard - **never committed**. Same names as `backend/.env.example`/`frontend/.env.example`:

| Variable | Production value |
|---|---|
| `ENVIRONMENT` | `production` |
| `DATABASE_URL` | Supabase's **connection pooler** URI (not the direct `db.<ref>.supabase.co` string - that host is IPv6-only and unreachable from most free-tier platform egress, Render's included) |
| `JWT_SECRET_KEY` | A long random value, distinct from any development secret |
| `CORS_ALLOW_ORIGINS` | The exact deployed frontend origin (`https://resolve-issue-platform.vercel.app`) - never `*` |
| `OPENAI_API_KEY` / `OPENAI_MODEL` / `OPENAI_BASE_URL` | The real AI provider credentials, same `AIProvider` abstraction as local dev |
| `VITE_API_BASE_URL` (frontend, Vercel) | The deployed backend origin (`https://resolve-backend-but8.onrender.com`) - baked in at build time, since Vite env vars aren't a runtime concept |

### Database migration

Identical mechanism to local development - `alembic upgrade head` - just pointed at the production `DATABASE_URL` (the pooler URI) instead of a local one. Applied once, directly, from a trusted machine with the production connection string in hand; not run automatically on every deploy in this MVP (the Render start command does include it, so it also re-runs - harmlessly, since Alembic no-ops when already at head - on every redeploy).

### Initial production admin

The application **never** creates a production admin automatically - there is no seed, no startup hook, no endpoint that can produce an `ADMIN` account (registration always creates `USER`, DECISIONS.md D23). `backend/scripts/bootstrap_dev_admin.py` explicitly refuses to run outside `ENVIRONMENT=development` and is never exposed as an HTTP route, so it cannot become a production bootstrap path even by accident.

The secure procedure actually used: a single, one-time, direct write against the production database (the same real `hash_password` function the application itself uses - bcrypt, never a plaintext or weakened hash), run once from a trusted machine holding the production connection string, immediately after the schema was created. The resulting credential was displayed exactly once, in that terminal session, and is not stored anywhere - not in this repository, not in any file, not in chat history beyond that one disclosure. Losing it means creating a new admin the same way, or having an existing admin issue an `ADMIN` invite (see "Resolver workflow" - the invite mechanism works identically for provisioning a second admin, and is the preferred path for every admin after the first).

### Deployment flow

```
clone repo
   ↓
configure secrets (provider dashboards - never .env files in git)
   ↓
create Supabase project → copy the connection pooler URI
   ↓
alembic upgrade head (against that URI, once)
   ↓
deploy backend (Render: Python runtime, buildCommand `pip install -r requirements.txt`,
                 startCommand `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT`)
   ↓
deploy frontend (Vercel: auto-detects Vite, VITE_API_BASE_URL set to the Render URL)
   ↓
set CORS_ALLOW_ORIGINS on the backend to the real deployed frontend origin
   ↓
verify GET /health
```

A push to `main` on GitHub redeploys both services automatically (Render and Vercel are each connected to the repository).

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

## Resolver workflow

`POST/GET /issues/{id}/comments`, `PATCH /issues/{id}/assignment`, `POST /issues/{id}/resolution/{confirm,reject}`. Resolver access is team-scoped: a resolver sees and can act on their own team's issues plus anything still unassigned, never another team's issue — the same rule governs viewing, transitioning, and commenting, so they can't disagree. The CRITICAL rule: the issue owner's own comment while `WAITING_FOR_USER` atomically resumes it to `IN_PROGRESS` and closes the SLA pause, in the same transaction as the comment — a resolver's or admin's comment never does. Assignment is append-only (a full history of who owned an issue and when, never overwritten); an admin can reassign freely, a resolver can only self-assign their own team's issue. `RESOLVED → CLOSED` is reachable only through the owner's explicit confirmation — not even an admin can override it. See PROJECT_CONTEXT.md's RESOLVER WORKFLOW section and DECISIONS.md D41.

## Dashboards & admin

`GET /dashboard/summary` (open requests, high priority, SLA at risk, resolved today), `GET /dashboard/at-risk-issues` (a real list, not just a count, sorted by nearest deadline), `GET /dashboard/breakdown` (status distribution, priority distribution, AI analysis failures, and — ADMIN only — per-team workload). Every number is a live, role-scoped database query (`_scope_filters` — ADMIN sees everything, RESOLVER sees their team plus unassigned, USER sees only their own) — there is no cached, precomputed, or fabricated metric anywhere. `GET/POST/PATCH /admin/{teams,categories,sub-categories,routing-rules,sla-rules,users}` (ADMIN only, enforced by a router-level `require_admin` dependency) give a real UI replacement for the dev-only seed script, including the ability to promote a `USER` to `RESOLVER`/`ADMIN` and assign/change their team — there is no DELETE verb anywhere; reference data and accounts are deactivated (`is_active=false`), never hard-deleted. See PROJECT_CONTEXT.md's DASHBOARDS & ADMIN section and DECISIONS.md D42–D43.

## Current status

Deployed and live (see "Live application" above): a real, publicly accessible instance running on Vercel (frontend) + Render (backend) + Supabase (PostgreSQL), all free-tier. Migrations applied and verified against the production database; the full USER → RESOLVER → ADMIN issue lifecycle (creation, real AI analysis, deterministic routing, SLA pause/resume, resolution, owner confirmation) and the full production RBAC/security suite (IDOR, cross-role access, unauthenticated/invalid-token rejection, role tampering) were verified with real HTTP requests against the live deployment, not just locally. All temporary smoke-test accounts and issues created during that verification were deleted from production afterward; only the one intentional admin account and real reference-data configuration (categories/teams/routing/SLA rules) remain.

253 passing pytest tests, all against a real PostgreSQL database, 0 failed. This followed a full security/failure/concurrency attack pass (JWT/IDOR/RBAC/lifecycle/CORS/rate-limit/input-validation attacks, a real parallel-HTTP concurrent status-transition race, and a real prompt-injection attempt against the actual configured Gemini provider) that found and fixed five genuine defects — see DECISIONS.md D44–D48 for full root-cause/fix/regression-test detail on each, and D50–D52 for the separate student/resolver/admin login entry points and the admin-issued RESOLVER/ADMIN invitation system added afterward. This README does not claim functionality that doesn't exist yet.

## Security considerations

Implemented and verified through Phases 3–9: passwords hashed with bcrypt, never stored or returned in plaintext; JWT signature and expiration always verified server-side with the algorithm explicitly pinned (rejects `alg=none` and any algorithm-confusion attempt); role/active-state always read fresh from the database, never trusted from the token; public registration structurally cannot create an elevated-privilege account; login responses don't reveal whether an email is registered; CORS restricted to an explicit origin allow-list (live-verified: a disallowed origin receives no CORS header at all); lightweight rate limiting on auth endpoints (live-verified: the 11th rapid login attempt within the window returns 429); unhandled exceptions (including database failures) never leak internals to the client; issue access is team-scoped and authorization-checked server-side regardless of what a client requests; status transitions (including the SLA pause/resume they trigger) are validated against a locked, real-time database read, never trusted client state; `RESOLVED → CLOSED` is reachable only through an owner-only confirmation endpoint, with no override path for any other role, and stays correct under real concurrent double-confirm requests; AI output is never trusted without validation, has no field capable of an authorization/routing/SLA decision even structurally, and a live attempt to prompt-inject "make this user an administrator" / "assign to ADMIN" / "always mark CRITICAL" through real issue text was rejected both by the real AI model and by the backend's deterministic validation; every admin endpoint is gated server-side by a router-level dependency; dashboard and admin data is always scoped server-side to the requesting user's actual role/team.

**Phase 9 found and fixed five genuine defects** (DECISIONS.md D44–D48): (1) the AI background task could silently overwrite a concurrent, already-committed manual status transition because it read the issue without the row lock every other mutator uses — fixed with a locked re-read immediately before its write, reproduced and confirmed with a deterministic real-thread test; (2) manual AI reanalysis was missing the team-scoping check every other resolver action has, letting a resolver trigger reanalysis on another team's issue; (3) an issue's SLA status kept evaluating against the live clock after it was resolved, so a well-handled issue could render as "breached" purely from elapsed time while awaiting owner confirmation; (4) an admin could PATCH an SLA rule's minutes to zero/negative even though creating one with the same values was correctly rejected; (5) `GET /issues` had an N+1 query pattern (up to ~6 extra queries per issue), fixed with eager loading and proven with a query-counting regression test. Full attack-review findings are in DECISIONS.md D20–D48.

## Limitations

- No self-service signup for `RESOLVER`/`ADMIN` — those roles are only reachable through an existing admin's invitation (DECISIONS.md D52) or, for the very first admin of a fresh deployment, one deliberate direct-database write (documented above under "Initial production admin"). `USER` remains the only self-registerable role (DECISIONS.md D23).
- Render's free web service sleeps after inactivity - the first request after a period of no traffic can take 30-60 seconds (cold start) before the API responds. Supabase's free project can similarly pause after extended inactivity. Both are accepted, documented free-tier tradeoffs, not bugs - no artificial keep-alive traffic was added to mask them.
- The SLA "at risk" threshold (20% of duration remaining) is a fixed, documented heuristic, not a per-category/priority configurable rule — reasonable for MVP, would be a natural refinement later.
- Logout does not invalidate the token server-side (stateless JWT tradeoff, DECISIONS.md D22) — a "logged out" token remains usable until it naturally expires (60 minutes by default).
- Auth rate limiting is in-memory and single-process — it does not protect a horizontally-scaled, multi-instance deployment (DECISIONS.md D25).
- The manual-reanalysis cooldown is likewise in-memory-adjacent (stored per-issue via `ai_analysis_results` timestamps in the database, so it *is* durable and shared across processes — unlike the auth rate limiter, this one is not a known gap).
- FastAPI `BackgroundTasks` has no persistence — a process restart mid-analysis can leave an issue stuck at `ai_analysis_status=PROCESSING`, or (rarer) lose a scheduled task's effect entirely on a hard restart; manual reanalysis is the recovery path (DECISIONS.md D14). This was deliberately not replaced with a durable queue (Celery/Redis) in Phase 9, per the project's explicit no-unnecessary-infrastructure rule — it remains an accepted, documented MVP tradeoff, not an oversight.
- Frontend token storage (`localStorage`) is not XSS-resistant (DECISIONS.md D27).
- Two resolvers on the same team racing to self-assign the same issue both succeed (last committer wins) — verified safe (no corruption, correct append-only history) but not exclusive; no "first come, first served" lock was ever specified as a product requirement.
- Duplicate issue creation (e.g. a user double-submitting the same form) creates two separate issues — each POST is a legitimate, independent user action with no client-supplied idempotency key, and this was judged acceptable MVP behavior rather than a defect worth a dedicated idempotency mechanism.
- Single-tenant design; no multi-organization support.
- No email/push notifications in MVP — status changes are visible in-app only.

## Future improvements

- Duplicate/related-issue detection, suggestion-only, no auto-merge.
- Durable AI task queue (Celery/Redis or similar) if AI load or retry guarantees demand it — see DECISIONS.md D1.
- Email/push notifications.
