# PROJECT_CONTEXT.md

> Living document. Update after every major milestone. This is the single source of truth for what Resolve is, what's been decided, and what's left.

## PROJECT NAME
Resolve — Intelligent Issue Resolution Platform

## PROBLEM
Organizations receive many complaints and service requests from users. These are often manually categorized, assigned to the wrong team, forgotten, duplicated, or resolved slowly, and the person who submitted the request has no visibility into what's happening to it. Resolve centralizes intake, uses AI to understand and structure each request, and routes it to the right team under deterministic business rules and SLA tracking, giving both the requester and the organization full visibility into the issue lifecycle.

## USERS
- **User** — registers, logs in, creates issues, views own issues, tracks status, comments, confirms resolution.
- **Resolver** — views assigned/team issues, updates status, comments, records resolution.
- **Admin** — views all issues, manages users/teams/categories, assigns/reassigns issues, views SLA data and analytics.

Role-based authorization is enforced on the backend for every endpoint; the frontend only reflects it for UX.

## REQUIREMENTS

### Explicit (from project brief)
- JWT auth, hashed passwords, RBAC enforced server-side.
- Issue creation with backend validation.
- AI classification (category, sub_category, priority, summary, reasoning) via structured LLM output, validated before use/storage, never trusted blindly.
- Configurable categories/sub-categories/teams (not hardcoded enums scattered through the app).
- Deterministic backend rules layered on top of AI suggestions (forced routing, keyword priority bumps, SLA calculation) — AI advises, backend decides.
- Controlled status lifecycle with server-side transition validation and full history: `OPEN → TRIAGED → ASSIGNED → IN_PROGRESS → WAITING_FOR_USER → RESOLVED → CLOSED`. This is the **business** lifecycle and is never mixed with AI processing state (see below).
- A separate `ai_analysis_status` field (`PENDING → PROCESSING → COMPLETED | FAILED`) tracks the AI pipeline independently of the issue's business status. An issue is always usable — viewable, commentable, manually triageable — regardless of where its AI analysis stands.
- SLA timer per issue, "at risk" visibility.
- Comments/communication thread on an issue.
- Resolution recording + explicit user confirmation before closing.
- Role-based dashboards (user, resolver, admin), team management, analytics, profile/settings.
- AI provider abstracted behind an interface (OpenAI-compatible), swappable later.
- Graceful AI failure: issue is still created, marked `AI_ANALYSIS_PENDING`, never a fabricated AI response.
- PostgreSQL only (no SQLite), SQLAlchemy models, migrations, proper FKs/indexes/timestamps.
- Docker + docker-compose for local dev.
- pytest backend test coverage; frontend tests where useful.
- No fake/demo data in the production path; any dev seed data isolated in an explicit dev-only script.
- Enterprise-neutral, non-"AI startup" UI using the specified warm-neutral palette.
- README, PROJECT_CONTEXT.md, DECISIONS.md, .env.example.
- Duplicate-issue detection deferred until MVP is stable; suggestion-only, never auto-merge.

### Implicit (inferred, to be confirmed as work proceeds)
- Single-organization deployment for MVP — no multi-tenant org switching.
- Teams map to categories/sub-categories through an admin-managed routing rule table, not hardcoded if/else.
- General audit trail: status history + assignment history double as an admin audit log.
- Basic abuse protection on login/issue-creation endpoints (rate limiting) is expected of a production-quality backend.
- AI is not re-invoked on every page view — classification runs once per issue (plus explicit manual re-run), to control cost and latency.
- Pagination on all list endpoints (issues, users, teams) once data volume matters.
- Consistent UTC timestamps everywhere SLA math happens.

## ASSUMPTIONS (defaults chosen for an FDE learning project; revisit if wrong)
- One organization, one deployment — no billing/tenancy layer.
- Categories, sub-categories, teams, and SLA targets are seeded/managed through admin-facing config tables, not enums baked into code.
- An issue has exactly one *current* team/resolver at a time, exposed as a denormalized pointer on `issues` for fast reads, but every assignment/reassignment appends a new `issue_assignments` row (assigned_by, assigned_at, reason) — history is append-only and queryable, never overwritten.
- SLA targets are defined per (category, final_priority) pair in a `sla_rules` table — e.g., HIGH → 4h first response / 24h resolution — looked up deterministically by `RoutingService` after the final priority is decided. The LLM never calculates or invents a duration.
- LLM provider for v1: an OpenAI-compatible chat completions API, called through a small `AIProvider` interface with no agent/RAG/framework layer on top — just request in, validated structured suggestion out. Swappable later without touching business logic.
- Email/push notifications are out of scope for MVP; status changes are visible in-app only. Flagged as a future improvement.
- Status transitions are restricted to an explicit allow-list enforced server-side (`OPEN→TRIAGED`, `TRIAGED→ASSIGNED`, `ASSIGNED→IN_PROGRESS`, `IN_PROGRESS→WAITING_FOR_USER`, `WAITING_FOR_USER→IN_PROGRESS`, `IN_PROGRESS→RESOLVED`, `RESOLVED→CLOSED`); every accepted transition writes an `issue_status_history` row. The frontend cannot cause a transition the backend doesn't independently validate.
- `RESOLVED → CLOSED` is never automatic. A resolver moving an issue to `RESOLVED` attaches resolution details; only the original submitter's explicit confirmation closes it. A rejected resolution returns the issue to an active state per the same transition table (not an arbitrary status). Any admin override of this confirmation step is itself a deterministic, explicitly coded rule and is recorded in `issue_status_history` like any other transition — never a silent bypass.
- SLA "pause" while `WAITING_FOR_USER` is modeled explicitly, not just implied by a fixed deadline: entering `WAITING_FOR_USER` opens a row in `sla_pauses`; leaving it closes that row and folds the elapsed pause duration into `sla_records.accumulated_pause_seconds`. At-risk/breach checks compare `now()` against `deadline + accumulated_pause_seconds + (elapsed time of any currently-open pause)` — i.e. the effective deadline is extended by exactly however long the clock was paused. Fully backend-computed; the LLM is never involved.
- A user's comment on an issue currently `WAITING_FOR_USER` automatically transitions it back to `IN_PROGRESS`, but only when the commenter is the issue's own submitting user — a resolver/admin commenting does not trigger it. The comment insert, the status update, the `issue_status_history` row (`trigger=auto_user_reply`), and the matching SLA-pause close all happen in one backend transaction, so the pause and the status can never drift apart.
- Status-transition endpoints never accept a client-supplied "current status" as truth. The handler loads the issue row with a row lock (`SELECT ... FOR UPDATE`) inside the transaction, validates the requested target against the allow-list using that freshly-read status, and only then updates — so two concurrent requests are serialized and the second one is judged against what the first one actually left behind, not against whatever the frontend last rendered.
- `POST /issues/{id}/reanalyze` (resolver-on-team or admin only) sets `ai_analysis_status=PENDING`, inserts a new `ai_analysis_results` row on completion (never overwrites a prior one), and is cooldown-limited (a fixed minimum interval since the last attempt) to prevent abuse. If the issue is still `OPEN` (never successfully routed), reanalysis behaves exactly like the original pipeline and can apply routing/SLA. If the issue has already progressed past `OPEN` (meaning it was routed and possibly hand-adjusted by a human), reanalysis only records a fresh AI opinion for review — it never silently re-routes or re-prioritizes an issue a human has already acted on.

## TECH STACK
- **Frontend**: React, TypeScript, Vite, Tailwind CSS.
- **Backend**: Python, FastAPI, Pydantic, SQLAlchemy.
- **Database**: PostgreSQL (no SQLite, including in tests where avoidable).
- **Auth**: JWT, secure password hashing (bcrypt/argon2), server-enforced RBAC.
- **AI**: OpenAI-compatible LLM API, isolated behind an `AIProvider` service interface.
- **Infra**: Docker, docker-compose for local dev.
- **Testing**: pytest (backend), targeted frontend tests.

## DATABASE (initial shape — finalized in Phase 2)
Core tables: `users`, `roles`, `teams`, `categories` (+ `sub_categories`), `routing_rules`, `sla_rules`, `issues`, `issue_comments`, `issue_status_history`, `issue_assignments`, `sla_records`.
All tables carry `created_at`/`updated_at`; foreign keys and indexes added where lookups are frequent (issue owner, assigned team, status, priority).

`issues` carries two independent state fields: `status` (business lifecycle, server-transition-validated) and `ai_analysis_status` (`PENDING | PROCESSING | COMPLETED | FAILED`, mirroring the latest row in `ai_analysis_results`). The backend's final decision (final category/sub_category/priority/team) lives on `issues` itself; every AI *suggestion* that led to it — including retries — is preserved separately, so what the AI proposed and what the system actually did are both auditable. All SLA/assignment/status timestamps are stored in UTC.

Two additional tables support the clarifications below:
- **`ai_analysis_results`** (append-only): `id, issue_id, attempt_number, status (COMPLETED|FAILED), category, sub_category, suggested_priority, summary, reasoning, error_message, created_at`. Each classification attempt — including manual reanalysis — inserts a new row instead of overwriting the last one, so prior AI opinions on an issue stay queryable.
- **`sla_pauses`**: `id, sla_record_id, paused_at, resumed_at (nullable), created_at`. At most one open row (`resumed_at IS NULL`) per SLA record at a time. `sla_records` gains `accumulated_pause_seconds` (running total, updated when a pause closes) alongside its fixed `first_response_deadline_at` / `resolution_deadline_at`.

`issue_status_history` gains a `trigger` field (`manual | auto_user_reply | ai_routing | admin_override`) alongside `changed_by` (nullable — automated transitions have no human actor) so every status change is traceable to why it happened, not just what changed.

## API ENDPOINTS
- `GET /health` — liveness check, no auth. Returns `{status, environment}`.

Remaining endpoints defined in detail during Phase 3 onward and recorded here as they're built (not before — avoids documenting endpoints that don't exist yet).

## ARCHITECTURE
Layered monolith (Option A, see DECISIONS.md): single FastAPI service, single React SPA, single Postgres database.
Backend layout: `app/{main, api, core, models, schemas, services, repositories, db, tests}`.
Frontend layout: `src/{components, pages, layouts, services, hooks, types, utils}`.

**AI/business separation (hard architectural rule):** the `AIProvider` service returns only a *suggestion* (category, sub_category, suggested_priority, summary, reasoning) as a validated Pydantic object. It never decides authorization, role, team access, final assignment, SLA, or whether an issue can be closed. A separate `RoutingService`/`RulesEngine` in `services/` is the only code allowed to decide the issue's actual team, final priority, and SLA target — it takes the AI suggestion as one input, applies deterministic rules (forced category→team mapping, keyword-based priority escalation, SLA-rule lookup), and that output is what gets persisted and acted on:

```
User Issue → AI suggestion → validate AI output → backend routing/rules → final category/team/priority/SLA → persist
```

Never `User Issue → AI → blindly trust → persist`.

**Issue creation never blocks on AI.** `POST /issues` authenticates, validates, inserts the issue row (`status=OPEN`, `ai_analysis_status=PENDING`), commits, and returns immediately. AI processing is triggered as a FastAPI background task *after* the commit, not inline in the request. The background task opens its **own** database session (the request-scoped session is never reused after the request ends) and: loads the issue, sets `ai_analysis_status=PROCESSING`, calls `AIProvider`, strictly validates the structured response, runs it through `RoutingService`, updates the issue's final category/team/priority, writes `issue_assignments`/`issue_status_history`/`sla_records` rows as needed, sets `ai_analysis_status=COMPLETED`, commits, and closes its session — with exceptions caught so a failure sets `ai_analysis_status=FAILED` (issue stays fully usable, never fabricated) instead of crashing the task or leaking a stuck session.

**AI output validation is strict, not best-effort.** Pydantic schemas define exactly what a valid suggestion looks like (category/sub_category from the configured set, priority from the allowed enum, non-empty summary/reasoning). Malformed JSON, missing fields, or out-of-vocabulary values are never silently coerced into something plausible — the backend either normalizes through an explicitly supported mapping or marks the analysis `FAILED` and leaves the issue in its current business state for manual triage.

## IMPORTANT DECISIONS
See DECISIONS.md for full reasoning. Summary: monolithic FastAPI + React (Option A) with FastAPI `BackgroundTasks` for AI chosen over a Celery/Redis worker split (Option B) and microservices (Option C) for MVP — revisit Option B only if AI load or retry guarantees demand it. AI processing state (`ai_analysis_status`) is kept strictly separate from the issue business lifecycle (`status`). No LangChain/RAG/vector DB/agent framework is used — the `AIProvider` is a plain, understandable abstraction over an OpenAI-compatible API.

## KNOWN BUGS
None yet — implementation has not started.

## CURRENT STATUS
Phase 1 (project setup) complete. Architecture approved by the developer, including four rounds of clarifications now recorded as D1–D14 in DECISIONS.md (AI/business separation, separate AI-analysis vs. business status, SLA pause/resume, concurrency handling, manual reanalysis, BackgroundTasks limitation).

Verified working: backend (FastAPI) boots and serves `GET /health`, with a passing pytest suite; frontend (React + Vite + Tailwind v4) builds and renders, calling the backend health check on load; the full stack (`db` + `backend` + `frontend`) builds and runs together via `docker compose up`, confirmed end-to-end (backend and frontend both reachable, Postgres container healthy). No database models, auth, issue workflow, or AI integration exist yet — that's Phase 2 onward.

## PENDING TASKS
- Phase 2: database schema + Alembic migrations (`users, roles, teams, categories, sub_categories, routing_rules, sla_rules, issues, issue_comments, issue_status_history, issue_assignments, sla_records, sla_pauses, ai_analysis_results`).
- Phase 3: authentication + RBAC.
- Phases 4–11: per the roadmap in the initial architecture discussion (issue creation → lifecycle → dashboards → AI classification → SLA/routing → testing/security → duplicate detection → deployment/docs).

## CONSTRAINTS
- No SQLite as a Postgres substitute, anywhere.
- No hardcoded categories/teams in application logic.
- No demo/fake data in the production code path.
- No secrets in source; `.env.example` only.
- AI output must always be validated before storage/use; never trusted blindly.
- Backend must independently enforce every authorization rule the frontend implies.
- UI must follow the specified warm-neutral, non-"AI startup" visual direction.
