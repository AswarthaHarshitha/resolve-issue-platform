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
- SLA "pause" while `WAITING_FOR_USER` is modeled explicitly, not just implied by a fixed deadline: entering `WAITING_FOR_USER` opens a row in `sla_pause_intervals`; leaving it closes that row and folds the elapsed pause duration into `sla_records.accumulated_pause_seconds`. At-risk/breach checks compare `now()` against `deadline + accumulated_pause_seconds + (elapsed time of any currently-open pause)` — i.e. the effective deadline is extended by exactly however long the clock was paused. Fully backend-computed; the LLM is never involved. The database itself (not just application logic) forbids overlapping or backwards pause intervals — see DECISIONS.md D19.
- A user's comment on an issue currently `WAITING_FOR_USER` automatically transitions it back to `IN_PROGRESS`, but only when the commenter is the issue's own submitting user — a resolver/admin commenting does not trigger it. The comment insert, the status update, the `issue_status_history` row (`trigger=auto_user_reply`), and the matching SLA-pause close all happen in one backend transaction, so the pause and the status can never drift apart.
- Status-transition endpoints never accept a client-supplied "current status" as truth. The handler loads the issue row with a row lock (`SELECT ... FOR UPDATE`) inside the transaction, validates the requested target against the allow-list using that freshly-read status, and only then updates — so two concurrent requests are serialized and the second one is judged against what the first one actually left behind, not against whatever the frontend last rendered.
- `POST /issues/{id}/reanalyze` (resolver-on-team or admin only) sets `ai_analysis_status=PENDING`, inserts a new `ai_analysis_results` row on completion (never overwrites a prior one), and is cooldown-limited (a fixed minimum interval since the last attempt) to prevent abuse. If the issue is still `OPEN` (never successfully routed), reanalysis behaves exactly like the original pipeline and can apply routing/SLA. If the issue has already progressed past `OPEN` (meaning it was routed and possibly hand-adjusted by a human), reanalysis only records a fresh AI opinion for review — it never silently re-routes or re-prioritizes an issue a human has already acted on. (`ai_analysis_results` itself is a Phase 7 table, not built in Phase 2 — see the DATABASE section.)

## TECH STACK
- **Frontend**: React, TypeScript, Vite, Tailwind CSS.
- **Backend**: Python, FastAPI, Pydantic, SQLAlchemy.
- **Database**: PostgreSQL (no SQLite, including in tests where avoidable).
- **Auth**: JWT, secure password hashing (bcrypt/argon2), server-enforced RBAC.
- **AI**: OpenAI-compatible LLM API, isolated behind an `AIProvider` service interface.
- **Infra**: Docker, docker-compose for local dev.
- **Testing**: pytest (backend), targeted frontend tests.

## DATABASE (Phase 2 — implemented and tested)

13 tables, all with UUIDv4 primary keys (DECISIONS.md D15). Every table has `created_at`; mutable tables (config/business rows) also have `updated_at`. All timestamp columns are `TIMESTAMP WITH TIME ZONE`, written in UTC.

**Reference/config data** (admin-managed, never hardcoded in application logic):
- `roles` — `name` (unique). Seeded with `USER`/`RESOLVER`/`ADMIN` by an Alembic migration, not application code (DECISIONS.md D16).
- `teams` — `name` (unique), `description`, `is_active`.
- `categories` — `name` (unique), `description`, `is_active`.
- `sub_categories` — `category_id` (FK, RESTRICT), `name`, `is_active`. Unique on `(category_id, name)`. Also carries `UNIQUE(category_id, id)` solely so other tables can hold a composite FK back to a specific (category, sub_category) pair — see `routing_rules`/`issues` below and DECISIONS.md D17.
- `routing_rules` — `category_id` (FK), `sub_category_id` (nullable FK, composite with `category_id` into `sub_categories`), `team_id` (FK), `is_active`. Two partial unique indexes prevent duplicate rules: one category-wide catch-all per category (`sub_category_id IS NULL`), one per specific sub-category (`sub_category_id IS NOT NULL`) — a plain unique constraint can't express this because SQL treats `NULL`s as distinct from each other.
- `sla_rules` — `category_id` (FK), `priority`, `first_response_minutes`, `resolution_minutes`, `is_active`. Unique on `(category_id, priority)`. Durations, not fixed deadlines — the deadline is computed once, when an `sla_records` row is created.

**Users**:
- `users` — `email` (unique), `password_hash`, `full_name`, `is_active`, `role_id` (FK, RESTRICT), `team_id` (nullable FK, RESTRICT). Whether only resolvers may have a `team_id` is enforced in the Phase 3 service layer, not the database — DECISIONS.md D18 explains why.

**Core business entity**:
- `issues` — `owner_id` (FK), `title`, `description`, `status` (business lifecycle enum), `ai_analysis_status` (`PENDING|PROCESSING|COMPLETED|FAILED`, independent of `status` — DECISIONS.md D2), `priority` (nullable until routed), `category_id`/`sub_category_id` (nullable, composite-FK-checked against `sub_categories` exactly like `routing_rules`), `current_team_id`/`current_resolver_id` (nullable, denormalized pointer to the latest `issue_assignments` row), `resolved_at`, `closed_at`.

**Append-only history** (never updated, only inserted):
- `issue_comments` — `issue_id` (FK, CASCADE), `author_id` (FK), `body`.
- `issue_status_history` — `issue_id` (FK, CASCADE), `previous_status` (nullable — null only for the creation row), `new_status`, `trigger` (`SYSTEM_CREATE|MANUAL|AUTO_USER_REPLY|AI_ROUTING|ADMIN_OVERRIDE`), `changed_by_id` (nullable FK — automated transitions have no human actor), `note`.
- `issue_assignments` — `issue_id` (FK, CASCADE), `team_id` (FK), `resolver_id` (nullable FK), `assigned_by_id` (nullable FK — AI-routed assignments have no human actor), `reason`.

**SLA**:
- `sla_records` — one per issue (`UNIQUE(issue_id)`), `sla_rule_id` (FK), `sla_started_at`, `first_response_deadline_at`, `resolution_deadline_at` (all fixed at creation), `first_response_met_at`/`resolved_met_at` (nullable), `accumulated_pause_seconds` (maintained cache, see below).
- `sla_pause_intervals` — one row per `WAITING_FOR_USER` window: `sla_record_id` (FK, CASCADE), `paused_at`, `resumed_at` (nullable while open). A `CHECK` constraint forbids `resumed_at < paused_at`; a GiST exclusion constraint (`btree_gist` extension) forbids any two intervals for the same `sla_record` from overlapping — which also means at most one interval can be open at a time, since an open interval's range is treated as extending to infinity. Full reasoning in DECISIONS.md D19. `sla_records.accumulated_pause_seconds` is always re-derivable by summing this table's completed rows; it's a read-optimization cache, not a second source of truth.

**Text relationship map**:
```
roles ─┬─< users >─┬─ teams
       │           │
categories ─┬─< sub_categories
            ├─< routing_rules >─ teams
            │       (+ sub_categories, optional)
            └─< sla_rules

users ─< issues (owner)
categories/sub_categories ─< issues (optional, composite-FK checked)
teams/users ─< issues (current_team / current_resolver, denormalized)

issues ─┬─< issue_comments >─ users (author)
        ├─< issue_status_history >─ users (changed_by, nullable)
        ├─< issue_assignments >─ teams, users (resolver / assigned_by)
        └─1─ sla_records >─ sla_rules
                  └─< sla_pause_intervals
```

**AI history** (Phase 5):
- `ai_analysis_results` — append-only, one row per classification attempt (including manual reanalysis): `issue_id` (FK, CASCADE), `attempt_number`, `status` (`COMPLETED|FAILED`), `raw_category`/`raw_sub_category`/`raw_priority`/`summary`/`reasoning` (exactly what the AI said, preserved even on failure), `matched_category_id`/`matched_sub_category_id`/`matched_priority` (populated only when validated — composite-FK checked against `sub_categories` exactly like `issues`/`routing_rules`), `error_message`. Unique on `(issue_id, attempt_number)`. Full reasoning in DECISIONS.md D33.

**Deletion strategy** (DECISIONS.md D15): `RESTRICT` on every FK to a shared reference/config entity (roles, teams, categories, sub_categories, sla_rules, and every FK to `users`) — deactivate via `is_active` instead of deleting. `CASCADE` only for an issue's own owned-child rows (comments, status history, assignments, sla_records → sla_pause_intervals, ai_analysis_results) — if an issue is ever deleted, its own history goes with it since nothing else references those rows.

**Reference/config data**: still no production seed data beyond the three baseline roles (D16); categories/teams/routing/SLA rules are populated in dev via an explicitly isolated, ENVIRONMENT-gated convenience script (`backend/scripts/seed_dev_reference_data.py`, DECISIONS.md D39) — never automatic, never production. An admin-facing management UI is Phase 8.

**Migrations**: Alembic, three revisions — `initial schema` (13 tables, constraints, indexes, the `btree_gist` extension), `seed baseline roles`, and `add ai analysis results` (Phase 5). `alembic upgrade head` / `alembic downgrade base` are both verified to run cleanly and repeatably against a real PostgreSQL database (not SQLite, not `create_all()` — the test suite runs actual migrations against a dedicated `resolve_test` database each session).

## API ENDPOINTS
- `GET /health` — liveness check, no auth. Returns `{status, environment}`.
- `POST /api/v1/auth/register` — public. Creates a `USER`-role account (never anything else — no `role` field is even accepted). Rate-limited.
- `POST /api/v1/auth/login` — public. Returns a JWT access token + safe user profile. Rate-limited.
- `GET /api/v1/auth/me` — requires a valid JWT. Returns the caller's own profile (role, team) loaded fresh from the database.
- `POST /api/v1/auth/logout` — requires a valid JWT. Stateless: confirms the request, invalidates nothing server-side (see DECISIONS.md D22).
- `POST /api/v1/issues` — any authenticated user. Creates an issue (`status=OPEN`, `ai_analysis_status=PENDING`), commits, returns, **then** schedules AI analysis as a background task (DECISIONS.md D3, D32 superseded by D33–D39).
- `GET /api/v1/issues` — any authenticated user. Paginated, optional `status` filter. A `USER` only ever sees their own issues (forced server-side); `RESOLVER` sees their own team's issues plus anything still unassigned; `ADMIN` sees all (team-scoped — DECISIONS.md D41, narrowing D29).
- `GET /api/v1/issues/{id}` — owner, `RESOLVER` on the issue's team (or if it's unassigned), or `ADMIN`. 404 if the issue doesn't exist, 403 if it exists but the caller can't see it.
- `PATCH /api/v1/issues/{id}/status` — `RESOLVER`/`ADMIN` only, and (for a `RESOLVER`) only on their own team's issue. Validates the target against the D8 transition table using a freshly row-locked read (D12/D31); structurally cannot reach `CLOSED` (reserved for the confirmation flow — D30, D41).
- `POST /api/v1/issues/{id}/reanalyze` — `RESOLVER`/`ADMIN` only. 404/403/409 (already `PROCESSING`)/429 (`Retry-After` header, cooldown) as appropriate; on success, `202` and a new background analysis attempt. Only re-routes if the issue is still `OPEN` (DECISIONS.md D13, D38).
- `POST /api/v1/issues/{id}/comments` / `GET /api/v1/issues/{id}/comments` — anyone who can access the issue. Posting a comment as the issue's owner while it is `WAITING_FOR_USER` atomically resumes it to `IN_PROGRESS` and closes the SLA pause (DECISIONS.md D11, D41) — no one else's comment does.
- `PATCH /api/v1/issues/{id}/assignment` — `ADMIN` (any team/resolver, with the resolver validated to belong to the target team) or `RESOLVER` (self-assign only, own team only). Every call appends a new `issue_assignments` row (DECISIONS.md D7, D41).
- `POST /api/v1/issues/{id}/resolution/confirm` / `.../reject` — issue owner only, even an `ADMIN` cannot call these. Confirm: `RESOLVED → CLOSED`. Reject: `RESOLVED → IN_PROGRESS` (DECISIONS.md D9, D41).
- `GET /api/v1/issues/{id}/history` — anyone who can access the issue. The status-history rows, in order, for the activity timeline.
- `GET /api/v1/issues/{id}/ai-analysis` — anyone who can access the issue. The most recent `ai_analysis_results` row (`null` if none yet) — summary, reasoning, raw vs. matched values.
- `GET /api/v1/dashboard/summary` / `/at-risk-issues` / `/breakdown` — any authenticated user, scoped identically to issue listing. Real counts/lists only, never placeholders (DECISIONS.md D43).
- `GET/POST/PATCH /api/v1/admin/{teams|categories|.../sub-categories|routing-rules|sla-rules}`, `GET/PATCH /api/v1/admin/users/{id}` — `ADMIN` only, router-level `require_admin`. No hard deletes — `is_active` only. This is the real replacement for manually inserting resolver/admin accounts into the database (DECISIONS.md D42).
- `GET /api/v1/_rbac-demo/{user-only|resolver-only|admin-only|resolver-or-admin}` — still temporary for the `user-only`/`resolver-only`/`resolver-or-admin` combinations, which still have no real single-purpose endpoint to test against; the `admin-only` case is now also covered for real by `/admin/*` (DECISIONS.md D42).

Remaining endpoints defined in detail as later phases build them.

## AUTHENTICATION & RBAC (Phase 3 — implemented and tested)

**Flow**:
```
Client → POST /auth/register or /auth/login → FastAPI
  → validate credentials (Pydantic + bcrypt) → PostgreSQL (users, roles)
  → JWT issued (register auto-logs-in the frontend by calling login next)
  → Client stores token (localStorage) → attaches Authorization: Bearer <token>
  → Protected API → get_current_user: verify JWT signature/expiry
    → reload user from PostgreSQL by sub → check is_active
    → RBAC: require_role/require_any_role check current_user.role.name
    → Endpoint handler runs
```

**JWT claims** (DECISIONS.md D21): `sub` (user UUID), `iat`, `exp` — deliberately no `role`. Every protected request reloads the user from PostgreSQL, so a role change or deactivation takes effect on the next request, not after the token expires.

**Password hashing**: bcrypt via passlib (DECISIONS.md D26).

**Role model** (DECISIONS.md D20): `roles` table is the source of truth (seeded by migration, D16); `app/core/roles.py`'s `RoleName` constants are the code-facing handle, used everywhere instead of string literals.

**RBAC**: `app/core/deps.py` — `get_current_user`, `require_role(name)`, `require_any_role(*names)`. Role checks are exact-match, not hierarchical (ADMIN does not implicitly gain RESOLVER access or vice versa). Phase 3 is role-level only; resource-level checks (issue ownership, team membership) are deferred until issue endpoints exist in Phase 4 (DECISIONS.md D24).

**Logout**: stateless MVP — client discards the token; the server performs no revocation (DECISIONS.md D22).

**Rate limiting**: in-memory, single-process, fixed-window (10 attempts/60s by default) on `/auth/login` and `/auth/register` (DECISIONS.md D25) — explicitly not a distributed limiter.

**CORS**: explicit origin allow-list from `CORS_ALLOW_ORIGINS`, never a wildcard (DECISIONS.md D28).

**Frontend**: `AuthContext` (React context) holds `user`/`isLoading`, hydrates from a stored token via `/auth/me` on load, exposes `login`/`register`/`logout`. `ProtectedRoute` redirects unauthenticated visitors to `/login` — UX only, not a security boundary (the backend enforces everything independently). Token stored in `localStorage`, attached via `Authorization` header (DECISIONS.md D27, XSS tradeoff documented explicitly).

## ISSUE LIFECYCLE (Phase 4 — implemented and tested)

**Creation**: any authenticated user → `IssueCreateRequest` (title ≤200 chars, description ≤5000 chars, both required non-empty) → `issue_service.create_issue` inserts the issue (`status=OPEN`, `ai_analysis_status=PENDING` — column defaults, nothing actively sets them) and a `SYSTEM_CREATE` `issue_status_history` row in the same transaction → commit → return → **then** (Phase 5) the route schedules `run_ai_analysis` as a `BackgroundTask`.

**Status transitions**: `PATCH /issues/{id}/status`, `RESOLVER`/`ADMIN` only. `app/services/status_transition_rules.py` holds the D8 allow-list as a pure, framework-agnostic function:
```
OPEN → TRIAGED → ASSIGNED → IN_PROGRESS ⇄ WAITING_FOR_USER → RESOLVED
```
`RESOLVED` has no outgoing transition in this table — reaching `CLOSED` is reserved for Phase 7's user-confirmation endpoint (DECISIONS.md D9, D30). Every accepted transition writes an `issue_status_history` row (`trigger=MANUAL`, `changed_by_id=`the acting resolver/admin).

**Concurrency**: `issue_repository.get_issue_by_id_for_update` uses `SELECT ... FOR UPDATE` inside the transition transaction, so a concurrent transition request on the same issue blocks until the first commits, then validates against whatever that first request actually left behind — never a stale or client-supplied status (DECISIONS.md D12, D31). Verified with a real two-thread, two-connection test against a genuinely shared row, not the test suite's usual rollback-isolated session.

**Authorization**: team-scoped as of Phase 7 (DECISIONS.md D41, narrowing D29) — see the RESOLVER WORKFLOW section below for the current rule.

## AI ANALYSIS & ROUTING (Phase 5 — implemented and tested)

**Flow** (DECISIONS.md D1, D3, D4, D33–D39):
```
POST /issues → issue committed (OPEN/PENDING) → response returned
  → BackgroundTask: run_ai_analysis(issue_id)
    → own DB session (never the request's)
    → ai_analysis_status = PROCESSING
    → AIProvider.classify() → structural-only AISuggestion (or raises)
    → ai_validation.validate_ai_suggestion() → semantic check against real
      categories/sub_categories/priority (or raises AIValidationError)
    → routing_service.route_issue() [only if issue.status == OPEN]:
        final priority = AI suggestion + deterministic escalation keywords
        category/sub_category set → OPEN→TRIAGED (history row)
        routing_rules lookup → team found? → current_team_id set,
          issue_assignments row, TRIAGED→ASSIGNED (history row)
        sla_rules lookup → found? → sla_records row created
    → ai_analysis_results row written (COMPLETED or FAILED, raw + matched)
    → ai_analysis_status = COMPLETED
  → any exception anywhere in this chain → ai_analysis_status = FAILED,
    issue otherwise untouched, never a fabricated result
```

**AI is advisory only**: `AISuggestion` (`app/services/ai_provider.py`) has exactly five fields — `category, sub_category, priority, summary, reasoning` — no team, no role, no SLA, nothing capable of an authorization or routing decision even in principle (asserted directly by `test_ai_suggestion_has_no_authority_over_authorization_or_team_assignment`). `RoutingService` is the only code that decides final category/priority/team/SLA, and it's driven by database configuration (`routing_rules`, `sla_rules`), not a hardcoded chain.

**Provider**: `OpenAICompatibleProvider`, configurable `OPENAI_BASE_URL` — verified live against both the real OpenAI shape and Google's Gemini OpenAI-compatibility endpoint during this phase's manual testing (DECISIONS.md D34).

**Validation**: strict, with exactly two explicit normalizations (case-insensitive category/sub-category/priority matching) and no others — an unmatched category or priority is a hard `FAILED`, an unmatched sub-category degrades gracefully to "category only" (DECISIONS.md D35).

**Deterministic priority escalation**: whole-word keyword matching (`\bkeyword\b`, not substring) bumps LOW/MEDIUM to HIGH for text containing "outage," "down," "cannot access," etc. — a real bug (naive substring matching falsely triggering on "dropdown") was caught by this phase's own tests and fixed (DECISIONS.md D36).

**Missing configuration is never silently dropped**: no `routing_rule` for a category → issue stays `TRIAGED`, unassigned, fully visible (not `ASSIGNED`, not hidden). No `sla_rule` → analysis still `COMPLETED`, just no `sla_records` row. Both are treated as an operational configuration gap, not a failure of the issue or the AI.

**Manual reanalysis**: `POST /issues/{id}/reanalyze`, resolver/admin only, cooldown-limited (429 + `Retry-After`), rejects if already `PROCESSING` (409). Only re-routes if the issue is still `OPEN`; on an already-progressed issue, it only records a fresh `ai_analysis_results` attempt without touching the issue (DECISIONS.md D13, D38).

**Dev reference data**: `backend/scripts/seed_dev_reference_data.py` — explicit, `ENVIRONMENT=development`-gated, idempotent. The only way `routing_rules`/`sla_rules`/`categories` get populated before Phase 8's admin UI exists (DECISIONS.md D39).

## SLA ENGINE (Phase 6 — implemented and tested)

**Pause/resume**: wired directly into `issue_service.transition_status` (DECISIONS.md D40) — entering `WAITING_FOR_USER` calls `sla_service.open_pause`; leaving it (`WAITING_FOR_USER → IN_PROGRESS`) calls `sla_service.close_pause`, both inside the same row-locked transaction as the status change itself, so a pause and its triggering transition can never drift apart. `close_pause` folds the closed interval's duration into `sla_records.accumulated_pause_seconds` (the D19 cache); `sla_pause_intervals` remains the source of truth.

**Computation**: `sla_service.compute_sla_status(sla_record, now=...)` — a pure function, no side effects, no reliance on anything held in process memory. Given `sla_record` with its `pause_intervals` loaded, it returns:
```
effective_elapsed = (now - sla_started_at) - accumulated_pause_seconds - (open pause's running duration, if any)
first_response_remaining = first_response_target_duration - effective_elapsed
resolution_remaining     = resolution_target_duration - effective_elapsed
at_risk   = 0 < remaining <= SLA_AT_RISK_THRESHOLD_FRACTION * target_duration   (default 20%)
breached  = remaining <= 0 (and not already "met")
```
Verified to reconstruct identically after a simulated restart (`session.expire_all()` + fresh reload) — proving no hidden in-memory state.

**API exposure**: every issue-returning endpoint (`create`, `get`, `list`, `PATCH .../status`) includes a computed `sla` object via a shared `build_issue_public()` helper (`first_response_deadline_at`, `resolution_deadline_at`, `effective_elapsed_seconds`, `accumulated_pause_seconds`, `is_paused`, and the four at-risk/breached booleans) — `null` if the issue was never routed to an `sla_rule`.

**Concurrency**: entering `WAITING_FOR_USER` inherits the same `SELECT ... FOR UPDATE` serialization as every other transition (D12/D31) — verified with a real two-thread/two-connection test that only one of two simultaneous `IN_PROGRESS → WAITING_FOR_USER` requests can succeed, and exactly one pause interval is ever opened. The database's exclusion constraint (D19) remains the final backstop.

## RESOLVER WORKFLOW (Phase 7 — implemented and tested)

**Team-scoped access** (DECISIONS.md D41, narrowing D29): `issue_service.can_access_issue` is the single place this is decided, reused by viewing, transitioning, and commenting alike.
```
ADMIN    → always
RESOLVER → issue.current_team_id is None (unassigned - visible to all, so it can be
            picked up) OR issue.current_team_id == user.team_id
USER     → issue.owner_id == user.id
```
`list_issues_for_user` mirrors this exactly, so a resolver's list and what they can individually open never disagree.

**Comments and the CRITICAL SPECIAL RULE**: `POST/GET /issues/{id}/comments`, access-gated by `can_access_issue`. `comment_service.add_comment` loads the issue under the same `SELECT ... FOR UPDATE` every other mutation uses; if the issue is currently `WAITING_FOR_USER` and the commenter is the issue's own owner, it atomically also transitions the issue to `IN_PROGRESS` and closes the SLA pause (reusing `sla_service.close_pause`) in the same transaction as the comment insert. A resolver, admin, or anyone else commenting never triggers this. Verified live: a resolver's comment while `WAITING_FOR_USER` left the issue unchanged; the owner's comment moved it to `IN_PROGRESS` and correctly closed the pause.

**Assignment**: `PATCH /issues/{id}/assignment`. `ADMIN` can set `team_id` and/or `resolver_id` to anything, with the assigned resolver validated to actually belong to the target team. `RESOLVER` can only self-assign (`resolver_id` must be their own id) on an issue already on their own team, and cannot change `team_id`. Every call appends a new `issue_assignments` row (never overwrites — D7); `issues.current_team_id`/`current_resolver_id` are updated in the same transaction. Assignment is independent of status — reassigning never itself changes `status`.

**Resolution confirmation** (DECISIONS.md D9, D30, D41): `POST /issues/{id}/resolution/confirm` and `.../reject`, both restricted to the issue's own owner — no admin override exists. Confirm requires `status == RESOLVED`, moves to `CLOSED`, sets `closed_at`. Reject requires the same precondition and returns the issue to `IN_PROGRESS` with an optional note. The generic `PATCH .../status` endpoint (resolver/admin-only) still cannot reach `CLOSED` under any circumstance — verified explicitly, not just assumed.

## DASHBOARDS & ADMIN (Phase 8 — implemented and tested)

**Admin provisioning** (DECISIONS.md D42): `PATCH /admin/users/{id}` is the real replacement for the manual-database-insert workaround every prior phase's manual verification depended on. Verified end to end over real HTTP: an ADMIN promotes a `USER` to `RESOLVER` with a team → the response and the database both show the new role/team immediately → the promoted user's next login reflects it (no new token trickery needed, D21's fresh-reload-per-request guarantee just applies) → the promoted user gets `RESOLVER` access and *not* `ADMIN` access → a plain `USER` attempting the same promotion endpoint on themselves or on someone else is rejected with 403. Role strings are validated against the real role set (not arbitrary text); promoting to `RESOLVER` without a team (new or already-set) is rejected; demoting away from `RESOLVER` clears the team.

**Admin CRUD**: teams, categories/sub-categories, routing rules, SLA rules — all "delete" operations are `is_active=False`, never a real `DELETE` (D15). Replaces `backend/scripts/seed_dev_reference_data.py` as the intended way to configure a real deployment; the seed script remains for local-dev convenience only.

**Dashboards** (DECISIONS.md D43): `GET /dashboard/summary` (open requests, high priority, SLA at risk, resolved today — all real queries, scoped identically to issue listing), `/at-risk-issues` (the actual prioritized list behind the at-risk count, sharing its scoping logic with the summary so they can never disagree), `/breakdown` (status distribution, priority distribution, AI-analysis-failure count, and — ADMIN only — team workload via `GROUP BY`). The frontend `DashboardPage` renders all of this: metric tiles, an at-risk worklist (resolver/admin only), a recent-issues table with status/priority/AI columns, and — for staff — status/priority distribution plus (admin only) team workload.

**Frontend**: the first real issue UI exists as of this phase — `IssuesListPage` (paginated, status-filterable, SLA/AI columns), `IssueCreatePage`, `IssueDetailPage` (AI analysis, SLA state, activity timeline from `/history`, comments with the owner-reply auto-resume behavior visible live, resolver actions gated by role, owner confirm/reject), and `AdminPage` (teams/categories/sub-categories/routing rules/SLA rules/users in one page, each with a small inline create form and list). `AppShell` provides the sidebar+topbar layout with a bottom nav fallback below the `sm` breakpoint, since the sidebar is hidden there. Every list/table wrapper uses `overflow-x-auto` rather than clipping, so no table can force horizontal page scroll on a narrow viewport.

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
See DECISIONS.md for full reasoning. Summary: monolithic FastAPI + React (Option A) with FastAPI `BackgroundTasks` for AI chosen over a Celery/Redis worker split (Option B) and microservices (Option C) for MVP — revisit Option B only if AI load or retry guarantees demand it. AI processing state (`ai_analysis_status`) is kept strictly separate from the issue business lifecycle (`status`). No LangChain/RAG/vector DB/agent framework is used — the `AIProvider` is a plain, understandable abstraction over an OpenAI-compatible API. Database (Phase 2): UUIDv4 keys everywhere, RESTRICT-vs-CASCADE deletion split, composite FKs for category/sub-category integrity, and a GiST exclusion constraint for SLA pause intervals — see D15–D19. Auth (Phase 3): JWT carries no role claim, role/is_active always reloaded from the database per request, stateless logout, localStorage token storage, in-memory single-process rate limiting — see D20–D28. Issues (Phase 4): `SELECT FOR UPDATE`-backed transition validation — see D29–D32. AI/routing (Phase 5): `ai_analysis_results` built now, structural-vs-semantic validation split, whole-word priority-escalation matching, injectable provider/session for testability, reanalyze cooldown/scope rules, dev-only reference-data seed — see D33–D39. SLA (Phase 6): pause/resume atomic with the triggering transition, pure DB-reconstructable computation, 20%-remaining at-risk threshold — see D40. Resolver workflow (Phase 7): team-scoped access narrowing D29, append-only assignment, atomic owner-reply auto-resume, owner-only confirm/reject — see D41. Dashboards & admin (Phase 8): real admin provisioning closes the manual-DB-insert gap, no hard deletes, every dashboard number from a real scoped query, at-risk exposed as a list not just a count — see D42–D43.

## KNOWN BUGS
None currently known. (One real bug — naive substring keyword matching in priority escalation — was found and fixed during Phase 5; see DECISIONS.md D36. One test-timing bug — an SLA-at-risk test assumed a 1-minute SLA would be "immediately" at risk without accounting for the 20%-remaining threshold — was found and fixed during Phase 8. Neither is currently open.)

## CURRENT STATUS
Phase 8 (dashboards + admin management) complete, on top of Phases 2–7. Architecture approved by the developer through four rounds of clarification (D1–D14), the database layer (D15–D19), authentication/RBAC (D20–D28), the issue domain (D29–D32), AI/routing (D33–D39), the SLA engine (D40), the resolver workflow (D41), and now dashboards/admin (D42–D43) — all in DECISIONS.md.

Verified working: 223 pytest tests passing (40 database + 47 auth/RBAC + 28 issue domain + 27 AI/routing/reanalyze + 15 SLA + 37 resolver workflow + 20 admin/dashboard + 3 history + 3 ai-analysis-endpoint + 3 dashboard-breakdown), all against a real PostgreSQL database. The admin-promotion workflow was additionally verified with a full live HTTP scenario end to end: admin lists teams → registers/logs in a fresh test user → promotes them to `RESOLVER` with a team → response and database both confirm the change → the promoted user re-authenticates and gets exactly `RESOLVER` access (not `ADMIN`) → a plain `USER` is rejected (403) from both self-promotion and modifying another user's role → an unauthenticated request is rejected (401). Zero bugs found in that flow. Frontend now has its first real issue UI (list/create/detail) and a dashboard/admin UI, verified via clean production build and dev-server boot, backend API responses, and Docker Compose — not a real browser (no browser-automation tool available in this session).

## PENDING TASKS
- Phase 9: security/failure/concurrency attack pass across everything built so far (auth, issues, AI, SLA, resolver workflow, admin).
- Phases 10–11: production deployment prep and actual deployment.

## CONSTRAINTS
- No SQLite as a Postgres substitute, anywhere.
- No hardcoded categories/teams in application logic.
- No demo/fake data in the production code path.
- No secrets in source; `.env.example` only.
- AI output must always be validated before storage/use; never trusted blindly.
- Backend must independently enforce every authorization rule the frontend implies.
- UI must follow the specified warm-neutral, non-"AI startup" visual direction.
