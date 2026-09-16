# DECISIONS.md

Architectural decisions for Resolve, with the reasoning behind each. Append new decisions as they're made; don't rewrite history — if a decision is later reversed, add a new entry that supersedes it and say so.

---

## D1 — Monolithic FastAPI + React over worker-queue or microservices

**Context**: three architecture options were considered — (A) a single FastAPI monolith with in-process background tasks for AI, (B) the same monolith plus a Celery/Redis worker for AI jobs, (C) full microservices per domain.

**Decision**: build Option A for the MVP.

**Reasoning**: this is a solo-developer, portfolio-scale, single-tenant system. Option C's cost (service boundaries, inter-service auth, distributed transactions, deployment complexity) buys scalability the project will never need at this stage, and would consume the learning budget that should go toward the actual product (AI/business separation, RBAC, SLA logic). Option B is the right answer once AI load or delivery guarantees demand it, but introducing Redis/Celery now would mean debugging infrastructure before the core workflow (Phases 1–9) even works. Option A keeps the AI call non-blocking (see D3) without that infrastructure, and the `AIProvider` interface (D4) means moving to B later is a service-layer swap, not a rewrite.

**Status**: active for MVP (Phases 1–9). Revisit if AI request volume, retry/backoff requirements, or multi-worker scaling become real needs.

---

## D2 — AI analysis state is separate from issue business status

**Context**: the issue's business lifecycle (`OPEN → TRIAGED → ASSIGNED → IN_PROGRESS → WAITING_FOR_USER → RESOLVED → CLOSED`) describes what's happening to the *request*. AI classification is a separate, orthogonal process that can succeed, fail, or still be running independent of where the issue sits in that lifecycle.

**Decision**: `issues` carries two independent fields — `status` (business lifecycle) and `ai_analysis_status` (`PENDING → PROCESSING → COMPLETED | FAILED`). Neither is derived from the other, and no code path is allowed to conflate them (e.g., there is no `status = AI_ANALYSIS_PENDING`).

**Reasoning**: mixing "what state is the request in" with "did the AI finish" produces a combinatorial mess (what does `WAITING_FOR_USER` + AI still running mean?) and, worse, tempts the system into gating business actions on AI completion. Keeping them separate guarantees an issue is always viewable, commentable, and manually triageable by a resolver/admin no matter what the AI pipeline is doing or whether it ever succeeds.

**Status**: active.

---

## D3 — Issue creation never blocks on the LLM

**Context**: LLM calls are slow (hundreds of ms to seconds) and occasionally fail or time out. The user-facing `POST /issues` request must not depend on that latency or availability.

**Decision**: the endpoint (1) authenticates, (2) validates input, (3) inserts the issue row with `status=OPEN`, `ai_analysis_status=PENDING`, (4) commits, (5) returns the created issue to the client, and only *after* the response path is committed does it (6) enqueue a FastAPI `BackgroundTask` to run AI analysis.

**Reasoning**: this guarantees issue creation succeeds and returns quickly regardless of AI provider health, matching the required fallback behavior (issue exists and is usable even if AI never completes). It also avoids holding a request thread/connection open for an external API call.

**Status**: active.

---

## D4 — Background AI task uses its own database session; AI is an advisor, not an authority

**Context**: reusing a request-scoped SQLAlchemy session inside a background task is unsafe — the session may be closed or in an inconsistent state once the request completes, and errors there are hard to diagnose. Separately, the AI's output must never directly drive authorization or persistence.

**Decision**: the background task opens a fresh DB session (independent of the request's), and performs, in order: load issue → set `ai_analysis_status=PROCESSING` → call `AIProvider` → strictly validate the structured response against a Pydantic schema → pass the validated suggestion into `RoutingService` (deterministic rules) → persist the `RoutingService`'s decision (final category/team/priority), plus any resulting `issue_assignments` / `issue_status_history` / `sla_records` rows → set `ai_analysis_status=COMPLETED` → commit → close the session. Any exception in this chain is caught, `ai_analysis_status` is set to `FAILED`, and the session is closed in a `finally` block — the issue itself is untouched and remains fully usable.

The `AIProvider` returns *only* a suggestion object: `category`, `sub_category`, `suggested_priority`, `summary`, `reasoning`. It has no ability to authorize actions, set roles, grant team access, decide final assignment, calculate SLA, or close an issue. The flow is always:

```
User issue → AI suggestion → validate → RoutingService (deterministic rules) → final category/team/priority/SLA → persist
```

never `User issue → AI → persist`.

**Reasoning**: this is the core trust boundary of the system. An LLM is probabilistic and can be manipulated (e.g., prompt injection via issue text) or simply wrong; treating its output as one validated input to a deterministic rules engine — rather than as the decision itself — means a bad AI response can degrade the *quality* of a suggestion but can never grant unauthorized access, misroute security-sensitive data, or corrupt SLA guarantees.

**Status**: active.

---

## D5 — Strict AI output validation; never fabricate a result

**Context**: LLMs can return malformed JSON, missing fields, or values outside the application's configured category/priority vocabulary.

**Decision**: every AI response is parsed against a Pydantic schema before any use. Categories/sub-categories are checked against the currently configured set (from the DB, not a hardcoded enum) and priority against the allowed set. Where a mismatch has an explicit, pre-defined normalization (e.g., case-insensitive match), it's applied; anything else fails validation. A failed validation sets `ai_analysis_status=FAILED` and stops — it never invents a plausible-looking category/priority to keep the pipeline moving.

**Reasoning**: "never blindly trust the LLM" only means something if failure is a real, handled outcome rather than papered over with a guessed default. A fabricated classification is worse than no classification, because it looks authoritative to a resolver who didn't write it.

**Status**: active.

---

## D6 — SLA is calculated deterministically from configured rules, never by the LLM

**Context**: SLA deadlines are a contractual/operational commitment; they cannot depend on a probabilistic model's arithmetic or judgment.

**Decision**: `sla_rules` is a DB-configured table keyed by `(category, priority)` → first-response and resolution deadlines. After `RoutingService` determines the final priority (AI suggestion + deterministic escalation rules, e.g. keyword-based bumps), the SLA deadline is looked up from this table and stored as UTC timestamps in `sla_records`. The AI is never asked for, and never supplies, a duration or deadline.

**Reasoning**: SLA math must be auditable and reproducible — "why does this issue have a 24h deadline" must always trace to a row in `sla_rules`, not to a model's output on a given day.

**Status**: active.

---

## D7 — Assignment history is append-only

**Context**: an issue's team/resolver can change over its lifetime (initial routing, reassignment, escalation); losing the history of who owned it and when would break auditability and SLA analysis.

**Decision**: `issue_assignments` is append-only. Each assignment/reassignment inserts a new row with `assigned_team`, `assigned_resolver` (nullable), `assigned_by`, `assigned_at`, and an optional `reason`. `issues` keeps a denormalized "current team / current resolver" pointer for fast reads, but that pointer is always derived from — and never a substitute for — the assignment history.

**Reasoning**: matches the same audit-trail principle as status history (D8) — anything that changes issue ownership must be reconstructable after the fact, both for admins and for future analytics (e.g., how often issues get reassigned).

**Status**: active.

---

## D8 — Status transitions are a server-side allow-list, every transition is recorded

**Context**: the frontend must never be the source of truth for what state changes are legal.

**Decision**: a fixed transition table is enforced in the backend:

```
OPEN → TRIAGED
TRIAGED → ASSIGNED
ASSIGNED → IN_PROGRESS
IN_PROGRESS → WAITING_FOR_USER
WAITING_FOR_USER → IN_PROGRESS
IN_PROGRESS → RESOLVED
RESOLVED → CLOSED
```

Any request for a transition not on this list is rejected with a 400, regardless of role. Every transition that *is* accepted writes a row to `issue_status_history` (previous status, new status, changed_by, changed_at, optional note).

**Reasoning**: this is the same "frontend is never the security/logic boundary" principle applied to workflow state, not just to auth — a compromised or buggy client must not be able to skip steps (e.g., `OPEN → CLOSED`) that the business process requires.

**Status**: active.

---

## D9 — RESOLVED → CLOSED requires explicit user confirmation

**Context**: a resolver believing an issue is fixed is not the same as the original submitter agreeing it's fixed.

**Decision**: a resolver transitions an issue to `RESOLVED` and attaches resolution details, but this does not close it. Only the submitting user's explicit confirmation performs `RESOLVED → CLOSED`. If the user rejects the resolution, the issue returns to an active state per the D8 transition table (not an arbitrary or ad hoc status). Any admin path that closes an issue without user confirmation (e.g., an inactivity timeout) is implemented as its own explicit, deterministic rule and is recorded in `issue_status_history` exactly like a normal transition — it is never a silent side effect.

**Reasoning**: the user's confirmation is the actual signal that the underlying problem is solved; auto-closing on the resolver's say-so would undermine the visibility guarantee that's the whole point of the product.

**Status**: active. The exact admin-override timeout policy (if/when added) will be documented here as its own decision when implemented.

---

## D10 — No AI frameworks beyond a plain `AIProvider` abstraction

**Context**: it would be easy to reach for LangChain, LangGraph, a vector database, RAG, or an agent framework for what is, functionally, a single structured-classification call.

**Decision**: the first implementation uses a small, hand-written `AIProvider` interface around an OpenAI-compatible chat completions API — request in, validated structured suggestion out. No agent framework, no RAG, no vector store, no multi-agent orchestration, unless a concrete Resolve requirement (e.g., duplicate-issue semantic search in a later phase) actually needs one.

**Reasoning**: this project's goal is to understand and demonstrate the engineering architecture — the AI/business separation, validation, and deterministic routing — not to demonstrate familiarity with an AI framework. A framework here would hide the exact boundary (D4) that's the point of the exercise. If duplicate detection (Phase 10) later needs embeddings/similarity search, that's evaluated on its own merits at that time, not pulled in preemptively.

**Status**: active.

---

## D11 — SLA pause/resume is modeled explicitly, and a user reply auto-resumes it

**Context**: comparing `now()` against a fixed SLA deadline is not sufficient once `WAITING_FOR_USER` time must be excluded — the exclusion has to be represented as data, not inferred, or "effective elapsed time" can't be audited or recomputed.

**Decision**: `sla_pauses` records each pause window (`paused_at`, `resumed_at`) against the issue's `sla_records` row; at most one open (`resumed_at IS NULL`) pause exists at a time. Entering `WAITING_FOR_USER` opens a pause; leaving it closes the pause and adds its duration to `sla_records.accumulated_pause_seconds`. At-risk/breach logic compares `now()` to `deadline + accumulated_pause_seconds + (now() - paused_at, if a pause is currently open)`. This is a fixed-deadline-plus-accumulated-offset model, not event sourcing — deliberately the simplest representation that's still fully auditable (every pause window is a queryable row) and fully backend-computed.

Separately: when the submitting user comments on an issue that is `WAITING_FOR_USER`, the backend automatically transitions it to `IN_PROGRESS` in the same transaction as the comment insert — verifying the commenter is the issue's owner, verifying the current status is actually `WAITING_FOR_USER` (via the same fresh-read-under-lock pattern as any other transition, D8), writing the `issue_status_history` row with `trigger=auto_user_reply`, and closing the open SLA pause. A resolver or admin commenting does not trigger this — only the submitting user's reply signals "I've responded, please continue."

**Reasoning**: `WAITING_FOR_USER` exists specifically to stop the SLA clock while the ball is in the user's court; the moment they reply, the ball is back in the resolver's court, and requiring the resolver to notice and manually flip the status would silently let SLA time accrue against them for a gap they don't control. Doing the transition and the pause-close atomically with the comment insert guarantees the two can never disagree (e.g., a comment saved but the pause left open due to a crash between two separate writes).

**Status**: active.

---

## D12 — Status transitions are validated against a freshly-locked read, never a client-supplied status

**Context**: two resolvers can act on the same issue concurrently; the transition check must reflect whatever the database actually holds at the moment of the write, not whatever either client last saw on screen.

**Decision**: transition endpoints take only the *target* status from the client — never an expected "current" status — and the handler reads the issue row with `SELECT ... FOR UPDATE` inside the same transaction as the update, validates `actual_current_status → target_status` against the D8 allow-list using that locked read, performs the update, and writes `issue_status_history` from that same actual previous status. A concurrent second request is blocked by the row lock until the first transaction commits, then evaluated against whatever the first request actually left behind.

**Reasoning / a nuance worth flagging**: this guarantees the check is never based on stale frontend state, which is the actual safety property being asked for. One consequence worth being explicit about: if resolver A moves `ASSIGNED → IN_PROGRESS` and resolver B then requests a move to `RESOLVED` (having last seen `ASSIGNED`), B's request is evaluated as `IN_PROGRESS → RESOLVED` against the current real state — which *is* a legal transition per the D8 table, so B's request succeeds rather than being rejected outright. That's correct, not a bug: the system is reacting to true current state, and `IN_PROGRESS → RESOLVED` is a legitimate operator action. What this mechanism actually prevents is a transition that's illegal *from the true current state* (e.g., B attempting to jump straight to `CLOSED`, or to `RESOLVED` while the true state is still `ASSIGNED` because A's request never happened) — those are rejected regardless of what B's UI displayed. B does still get a clear signal that state moved under them, because the returned issue reflects the real transition that was applied (`IN_PROGRESS → RESOLVED`), not the one B assumed (`ASSIGNED → RESOLVED`).

**Status**: active.

---

## D13 — Manual AI reanalysis: scope, safety, and abuse prevention

**Context**: `AI_ANALYSIS FAILED` (or a task lost to a process crash while `PROCESSING`, per D1/D4) needs a recovery path that a resolver or admin can trigger, without letting reanalysis silently undo triage work a human has already done, and without letting the endpoint be hammered.

**Decision**: `POST /issues/{id}/reanalyze`, restricted to a resolver on the issue's current team or an admin (never the submitting user). It sets `ai_analysis_status=PENDING` and triggers a new background task through the same pipeline as initial creation (D3/D4) — own DB session, strict validation, etc. Each attempt inserts a new `ai_analysis_results` row (`attempt_number` incrementing); prior attempts are never deleted or overwritten, so the full history of what the AI suggested over time stays queryable. It never touches `issue_status_history`/`issue_assignments` retroactively. A cooldown (fixed minimum interval since the last attempt, checked against the latest `ai_analysis_results.created_at`) rejects rapid repeated calls with 429.

Scope rule to avoid AI undoing human decisions: if the issue is still `status=OPEN` (meaning it was never successfully routed — the crash-recovery case this endpoint primarily exists for), reanalysis behaves exactly like the original pipeline and *can* apply routing/priority/SLA, because nothing human has happened yet to conflict with. If the issue has already moved past `OPEN` (it was routed, and plausibly hand-adjusted since), reanalysis only records a fresh suggestion in `ai_analysis_results` for a human to review — it does not re-run `RoutingService` or change the issue's current team/priority/SLA. A human decides whether to act on the new suggestion.

**Reasoning**: this keeps the endpoint genuinely useful as the MVP's only recovery mechanism for D5's stuck-`PROCESSING`/failed-task scenario, while staying consistent with D4's core rule that AI never directly overrides decisions the backend (or a human acting through it) has already made.

**Status**: active.

---

## D14 — FastAPI BackgroundTasks: known crash-recovery gap, accepted for MVP

**Context**: `BackgroundTasks` runs in-process with no persistence — if the server process dies after a task starts (e.g., mid-classification), the task is simply lost. Because `ai_analysis_status` is set to `PROCESSING` before the AI call and only updated to `COMPLETED`/`FAILED` after, a crash in that window leaves the issue stuck showing `PROCESSING` indefinitely, with no automatic retry.

**Decision**: accept this gap for MVP rather than introducing Redis/Celery (D1) to close it. The documented, user-facing recovery path is the manual reanalyze endpoint (D13) — a resolver/admin who notices an issue stuck in `PROCESSING` can trigger a fresh attempt. This limitation is stated plainly in the README and here, not hidden.

**Reasoning**: a durable queue with task tracking would close this gap properly, but doing so now repeats the reasoning in D1 — it's infrastructure the MVP's actual scale doesn't need yet, bought at the cost of complexity the learning project doesn't benefit from. A manual recovery button is an honest, sufficient MVP answer as long as it's documented as a known limitation rather than presented as a solved problem.

**Status**: active. Superseded automatically if/when D1 is revisited and a durable worker queue is introduced — at that point tasks would carry real retry semantics and this gap closes structurally instead of manually.

---

## D15 — Primary keys are UUIDv4 everywhere; deletion strategy is RESTRICT for shared reference data, CASCADE for owned history

**Context**: Phase 2 needed one consistent rule for primary keys, and an explicit answer to the attack-review question "what happens when a user/team/category is deleted while other rows still reference it?"

**Decision — primary keys**: every table uses a UUIDv4 primary key, generated application-side (`default=uuid.uuid4`, not a Postgres sequence or `gen_random_uuid()`). One rule for the whole schema is easier to reason about than mixing integer and UUID keys by table "importance," IDs are unpredictable/non-enumerable (a user can't guess `/issues/43` → `/issues/44`), and the ID is known before the row is even inserted, which is convenient when a request needs to reference an ID across more than one statement in the same transaction.

**Decision — deletion strategy**: two different `ON DELETE` behaviors are used deliberately, not inconsistently:
- **RESTRICT** for shared reference/config entities that other rows point to for their *meaning* — `roles`, `teams`, `categories`, `sub_categories`, `sla_rules`, and every reference from history/business rows back to a `user` (owner, author, changed_by, assigned_by, resolver, current_resolver). The database refuses the delete outright. The supported way to retire one of these is `is_active = false`, not deletion — this is exactly why `teams`, `categories`, and `sub_categories` all carry an `is_active` column. Users are never hard-deleted at all; deactivation is the only supported path, because a user row is referenced by potentially years of audit history that must remain valid.
- **CASCADE** for true owned-child rows that have no independent meaning without their parent — `issue_comments`, `issue_status_history`, `issue_assignments`, and `sla_records` (which in turn cascades to `sla_pause_intervals`) all cascade from `issues`. If an issue itself is ever deleted (not exposed via any Phase 2 API, but not forbidden at the schema level either), its own history has nothing left to be a history *of*, so it goes with it.

**Reasoning**: a single blanket cascade policy would be wrong in both directions — cascading from `categories` would silently destroy issue history when an admin deactivates a category, and restricting `issue_comments` from their issue would make it impossible to ever clean up an issue's own data. Splitting the two cases by "is this row's meaning independent of its parent" gives a rule that's easy to apply to new tables later, and every attack-review question about deletion in section 12 of the Phase 2 spec is answered by one of these two behaviors rather than an app-level check bolted on afterward.

**Status**: active.

---

## D16 — Roles are required reference data, seeded by a migration, not application code

**Context**: `USER` / `RESOLVER` / `ADMIN` must exist as `roles` rows before a single user can register (Phase 3), in every environment including production — but the project rules also forbid demo/fake data in the production path.

**Decision**: a dedicated Alembic migration (`seed baseline roles`, immediately after the schema migration) inserts exactly these three rows via `op.bulk_insert`, with a matching `downgrade()` that removes them by name. No other table is seeded this way in Phase 2.

**Reasoning**: this is reference data the application cannot function without, not sample/demo content — the distinction the project rules draw is between "data required for the app to work" and "fake business records" (fake users, fake issues), not between "migration" and "no data at all." Categories, sub-categories, teams, routing rules, and SLA rules are genuine admin-configured business decisions with no universally-correct default, so none of them are seeded here — they're deferred to an admin-facing flow (or an explicitly isolated dev-only convenience script) in a later phase, exactly as the project rules require for anything that isn't strictly necessary for the system to boot.

**Status**: active.

---

## D17 — Composite foreign keys enforce category/sub_category integrity at the database level

**Context**: the attack-review question "can an invalid sub-category/category combination be stored?" needed an answer stronger than an application-level check, per the Phase 2 instruction to prefer a database constraint wherever one can safely enforce the invariant.

**Decision**: `sub_categories` carries a `UNIQUE(category_id, id)` constraint (redundant with its own primary key, but required so another table can reference the *pair*). `issues` and `routing_rules` each declare a composite `ForeignKeyConstraint(["category_id", "sub_category_id"], ["sub_categories.category_id", "sub_categories.id"])` alongside their plain `category_id → categories.id` foreign key. Postgres's default `MATCH SIMPLE` semantics mean the composite constraint is automatically satisfied whenever `sub_category_id` is `NULL` (a category with no sub-category chosen yet is fine), but the moment `sub_category_id` is set, it is only valid if it actually belongs to the stated `category_id`.

**Reasoning**: this makes "IT / Plumbing" (a real sub-category, but of Facilities, not IT) impossible to store, full stop — no service-layer code has to remember to check it, and no future bug can skip the check. `routing_rules` gets the identical constraint for the same reason: a routing rule is exactly as vulnerable to this mismatch as an issue is.

**Status**: active.

---

## D18 — User/team pairing (only resolvers have a team) is an application-layer rule, not a database constraint

**Context**: `users.team_id` should conceptually only be set for `RESOLVER`-role users, but a Postgres `CHECK` constraint cannot reference another table's data (it would need to look up `roles.name` for `role_id`), and a trigger would be the only DB-level way to enforce it.

**Decision**: `team_id` is a plain nullable foreign key with no database-level rule tying it to `role_id`. The constraint "only resolvers have a team" will be enforced in the Phase 3 service layer (e.g. on user creation/role change), not the schema.

**Reasoning**: a trigger-based enforcement is possible but is exactly the kind of infrastructure this project's rules ask to avoid adding without a concrete need — the invariant is a business rule about *who should logically have a team*, not a referential-integrity concern that could corrupt other rows if violated (an admin user with a stray `team_id` set is a data-quality issue to catch in the service layer, not a threat to any other table's integrity). This is a deliberate, documented exception to "prefer a database constraint" — made because the constraint would require a trigger, not a plain `CHECK` or `FOREIGN KEY`, crossing the complexity line this project draws.

**Status**: active. Revisit if a data-quality problem in practice suggests the application-layer check isn't being applied consistently.

---

## D19 — `sla_pause_intervals` table, the `accumulated_pause_seconds` cache, and the no-overlap exclusion constraint

**Context**: SLA pause/resume (D11) needs to support multiple, independently-timestamped `WAITING_FOR_USER` windows per issue, be fully reconstructable after a restart, and make "can an issue have two simultaneously open pauses?" and "can two pause windows overlap?" impossible rather than merely checked.

**Decision**: `sla_pause_intervals` is a table beyond the original 12, one row per pause window (`sla_record_id`, `paused_at`, `resumed_at` nullable while open). Two database-level guarantees, not application checks:
- `CHECK (resumed_at IS NULL OR resumed_at >= paused_at)` — a pause can never be recorded as ending before it started.
- A PostgreSQL exclusion constraint, `EXCLUDE USING gist (sla_record_id WITH =, tstzrange(paused_at, COALESCE(resumed_at, 'infinity'), '[]') WITH &&)`, requiring the `btree_gist` extension (enabled once, in the initial migration). This single constraint does two jobs at once: it forbids any two intervals for the same SLA record from overlapping, *and*, because an open interval's range is treated as extending to infinity, it automatically forbids a second open interval from being created while one is already open — "at most one active pause at a time" falls out of the same constraint rather than needing a separate rule.

`sla_records.accumulated_pause_seconds` is a maintained cache of `SUM(resumed_at - paused_at)` over this table's *completed* rows for that record — it exists purely so an at-risk/breach check doesn't have to aggregate the pause table on every read. `sla_pause_intervals` remains the source of truth; the cache is always re-derivable from it.

**Reasoning**: this directly answers every SLA-related attack-review question with a schema-level guarantee instead of a promise that application code will always get it right: the full timeline (when did each pause start/end, is one currently open, what's the total) is reconstructable from durable rows alone, survives a server restart, and cannot be corrupted into an inconsistent state by a bug or a race between two concurrent requests — Postgres itself rejects the bad write. This is a small, well-understood use of a single Postgres extension, not event sourcing or new infrastructure, consistent with the Phase 2 instruction to avoid over-engineering the SLA data model while still getting the invariant enforced correctly.

**Status**: active. `ai_analysis_results` (an append-only table to preserve every AI suggestion, including reanalysis attempts, referenced in earlier architecture discussion as D13's persistence layer) is intentionally **not** created in Phase 2 — it belongs with AI classification itself in Phase 7, per the Phase 2 boundary excluding AI/LLM work. Phase 2 only adds the `ai_analysis_status` column on `issues` that D2 requires.

---

## D20 — Role representation: database is the source of truth, `RoleName` constants are the code-facing handle

**Context**: `roles` is a database table (D16), but application code — RBAC dependencies, the registration service, tests — needs a concrete way to say "the ADMIN role" without scattering the string literal `"ADMIN"` through every file.

**Decision**: `app/core/roles.py` defines a plain class, `RoleName`, with `USER`/`RESOLVER`/`ADMIN` string constants, plus ready-made dependency instances (`require_user`, `require_resolver`, `require_admin`, `require_resolver_or_admin`). Every authorization check, and the registration service's default-role lookup, references these constants — never a bare string. The `roles` table remains what a foreign key actually points at and what a lookup actually queries; the constants are purely a code-side convenience so a typo in a role name becomes a Python `NameError`/import failure instead of a silent authorization bug.

**Reasoning**: this satisfies both halves of the Phase 3 instruction — "the database should remain the source of truth for role identity" and "avoid magic strings scattered across endpoints" — without building a parallel Python enum that could drift from the database rows. If an admin ever adds a fourth role directly in the database, it would have no meaning to existing code until a corresponding constant and RBAC dependency were added deliberately — which is the correct behavior; a new role shouldn't silently gain authorization meaning nobody wrote.

**Status**: active.

---

## D21 — JWT claim design, always reloading the user from the database, and login response ordering

**Context**: three related trust decisions had to be made together: what goes in the token, what the backend trusts from it, and what a login attempt reveals to someone who doesn't yet have valid credentials.

**Decision**:
- The JWT payload is exactly `{"sub": "<user-uuid>", "iat": ..., "exp": ...}`. No `role`, no `team_id`, nothing else. `get_current_user` decodes and verifies the signature/expiration, then unconditionally re-loads the user from PostgreSQL by `sub` on *every* protected request, and checks `is_active` there — never on anything read out of the token payload.
- `authenticate_user` checks the email/password pair first; only if that succeeds does it check `is_active`. A wrong password against a disabled account gets the same generic `401 Incorrect email or password` as a wrong password against an active one. Only a caller who has already proven they know the correct password is told the account is specifically disabled.

**Reasoning**: embedding `role` in the token is a common pattern, but it creates exactly the "stale role" problem the Phase 3 spec calls out — an admin who gets demoted, or a resolver removed from a team, would keep their old permissions until the token naturally expired (up to 60 minutes by default) if anything trusted that claim. Reloading fresh from the database on every request means a role change or account deactivation takes effect on the *next* request, not after a token expires, at the cost of one extra indexed primary-key lookup per request — a cost worth paying for a correctness guarantee this important. The login-ordering rule prevents two different information leaks at once: enumerating valid email addresses (wrong password vs. unknown email look identical), and confirming a *guessed* account is disabled without the attacker ever proving they know its password.

**Status**: active.

---

## D22 — Logout: stateless MVP, client-side token discard only

**Context**: JWT access tokens are, by design, self-verifying and stateless — the server doesn't hold a session to destroy. "Logging out" a specific token before its natural expiration requires either a server-side revocation list (a database table or cache checked on every request) or accepting that a token remains valid until it expires regardless of what the client does.

**Decision**: `POST /api/v1/auth/logout` requires a valid token (so it fails cleanly for an already-logged-out or invalid session) and returns `204`, but performs no server-side revocation. The actual logout is the frontend discarding its stored token (`clearStoredToken()` in `AuthContext.logout()`). A test (`test_logout_does_not_invalidate_the_token_stateless_mvp_tradeoff`) asserts the same token still authenticates successfully immediately after calling `/logout` — documenting the real behavior rather than a claimed one.

**Reasoning**: a revocation list is the correct fix but is real infrastructure (a table checked on every single authenticated request, or a cache like Redis) that the Phase 3 spec explicitly says not to introduce without concrete need. The mitigation that *is* in place is a short token lifetime (60 minutes by default, `JWT_ACCESS_TOKEN_EXPIRE_MINUTES`) bounding how long a "logged out" token stays usable if it were somehow replayed. This is an explicit, documented MVP limitation, not a hidden one — see also README's Limitations section.

**Status**: active. If a real need for immediate server-side revocation emerges (e.g. a compromised-account response process), the minimal correct fix is a small `token_denylist` table keyed by JWT `jti` — not Redis — checked in `get_current_user`.

---

## D23 — Public registration cannot create an ADMIN or RESOLVER account

**Context**: the registration endpoint must never let a caller choose their own role.

**Decision**: `RegisterRequest` (the Pydantic schema for `POST /auth/register`) has no `role` field at all. `register_user()` always looks up the `USER` role and assigns it — there is no parameter, branch, or code path anywhere in the registration flow that could assign `RESOLVER` or `ADMIN`. If a client sends `"role": "ADMIN"` in the request body, Pydantic's default `extra="ignore"` behavior silently drops it before the service layer ever sees the payload (verified by `test_public_registration_cannot_create_admin`).

**Reasoning**: "don't trust a role sent by the client" is best enforced by never having a code path capable of accepting one, rather than by remembering to validate/reject it at the API boundary. RESOLVER/ADMIN account provisioning is deliberately out of scope for Phase 3 (no admin-facing user-management endpoint exists yet) — the only way such an account exists today is created directly in the database (exactly how this phase's manual RBAC verification was done). A controlled provisioning flow (e.g. an admin-only "create resolver" endpoint) is a future-phase concern once admin functionality exists.

**Status**: active.

---

## D24 — RBAC scope: role-level now, resource-level deferred; temporary `/_rbac-demo` endpoints

**Context**: Phase 3 has to prove role-based access control actually works over real HTTP, but the only resources that will eventually need *resource-level* authorization (e.g. "a USER may only view their own issues," "a RESOLVER may only act on issues assigned to their team") don't exist yet — issue endpoints are a later phase.

**Decision**: `app/core/deps.py` implements `get_current_user`, `require_role`, and `require_any_role` as general-purpose, reusable dependencies with no knowledge of any specific resource. `app/api/routes/rbac_demo.py` adds four throwaway endpoints (`/_rbac-demo/user-only`, `/resolver-only`, `/admin-only`, `/resolver-or-admin`) whose only purpose is giving the test suite (and this phase's manual verification) something real to send authenticated HTTP requests against. They are explicitly documented as temporary in their own module docstring and are expected to be deleted once Phase 4+ introduces real protected endpoints.

**Reasoning**: the Phase 3 spec is explicit that resource-level checks (issue ownership, team membership) must wait until there's an actual resource to check — building that logic now against nothing would be speculative and likely wrong once real requirements (e.g. exact issue-visibility rules) show up. The demo endpoints keep the RBAC dependency chain genuinely tested over HTTP (not just unit-tested by calling a dependency function directly) without pretending they're real product functionality.

**Status**: active, temporary by design. Remove `rbac_demo.py` when Phase 4's issue endpoints can take over as the real target for these tests.

---

## D25 — Rate limiting: in-memory, single-process, documented as a known limitation

**Context**: `/auth/login` and `/auth/register` need *some* protection against repeated automated attempts, but the project rules explicitly forbid adding Redis or similar infrastructure just for this.

**Decision**: `app/core/rate_limit.py` implements a small fixed-window limiter entirely in process memory (a dict of timestamps per client IP, guarded by a lock), applied as a FastAPI dependency on both endpoints. Limits are configurable via `AUTH_RATE_LIMIT_MAX_ATTEMPTS`/`AUTH_RATE_LIMIT_WINDOW_SECONDS` (defaults: 10 attempts per 60 seconds). Exceeding the limit returns `429`.

**Reasoning**: this is real protection for the single-process deployment this project actually runs (`uvicorn app.main:app`, one process, per `docker-compose.yml`), and it is honestly documented as exactly that — not claimed as anything more. It has two known gaps, stated plainly rather than glossed over: it resets on every process restart, and it is **not** shared across multiple worker processes or horizontally-scaled instances (`uvicorn --workers N` or multiple containers would each have their own independent counters, diluting the effective limit by a factor of N). A production deployment that actually scales horizontally would need a shared store (Redis, or a database-backed counter) — deliberately not built now, per the "no unnecessary infrastructure" rule, since this project runs as a single process today.

**Status**: active. Revisit if/when the deployment model changes to multiple worker processes or instances.

---

## D26 — Password hashing: bcrypt via passlib

**Context**: passwords must never be stored in a reversible or fast-to-brute-force form.

**Decision**: `passlib.context.CryptContext(schemes=["bcrypt"])`. `bcrypt` is pinned to `4.0.1` in `requirements.txt` alongside `passlib==1.7.4` — passlib 1.7.4's bcrypt backend-detection code is incompatible with `bcrypt>=4.1` (a well-known upstream issue), so the version is pinned explicitly rather than left to float and break on a future `pip install`.

**Reasoning**: bcrypt is a purpose-built, adaptive password hash (configurable work factor, built-in per-password salt) as opposed to a general-purpose fast hash like SHA-256, which would make brute-forcing leaked hashes far cheaper. `passlib` is a thin, well-tested wrapper rather than hand-rolling salt/work-factor handling. This is a standard, unsurprising choice — no bespoke or exotic hashing scheme.

**Status**: active.

---

## D27 — Frontend token storage: `localStorage` + `Authorization` header, with the XSS tradeoff documented rather than ignored

**Context**: the SPA needs to hold onto the JWT access token between page loads and attach it to every API request. Two realistic options existed: `localStorage` (read by JavaScript, sent manually via an `Authorization` header) or an `httpOnly` cookie (invisible to JavaScript, sent automatically by the browser, but requiring CSRF protection and backend cookie-issuing/CORS-credentials configuration).

**Decision**: the token is stored in `localStorage` (`frontend/src/services/tokenStorage.ts`) and attached manually via `Authorization: Bearer <token>` on every request (`frontend/src/services/api.ts`).

**Reasoning**: this keeps the backend fully stateless with no cookie infrastructure, no CSRF token plumbing, and works identically for a browser client or any other HTTP client — appropriate for an MVP with no existing session/cookie infrastructure to build on, and consistent with "no unnecessary infrastructure." The honest tradeoff: this is **not** XSS-resistant — a successful script injection on the frontend's origin could read `localStorage` and exfiltrate the token, usable for up to `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` (60 minutes by default). A hardened production deployment would move the token into an `httpOnly`, `Secure`, `SameSite=strict` cookie set by the backend at login, paired with CSRF protection (e.g. a double-submit cookie) — a real architectural change to the login/session flow, not a small tweak, which is why it's deferred rather than half-implemented now.

**Status**: active. Revisit before any production deployment that handles real user data at scale.

---

## D28 — CORS: explicit origin allow-list, never a wildcard

**Context**: the React frontend and FastAPI backend run on different origins (`localhost:5173` vs `localhost:8000` in dev), so the browser enforces CORS on every request unless the backend explicitly allows it.

**Decision**: `CORSMiddleware` (configured in Phase 1, reaffirmed here) reads `allow_origins` from `settings.cors_origins_list`, itself parsed from the `CORS_ALLOW_ORIGINS` environment variable (comma-separated) — never a hardcoded `["*"]`. `.env.example` ships with `http://localhost:5173` for local development; a production deployment sets this to the real frontend domain(s). Verified by `tests/test_cors.py`, which asserts the configured origin gets reflected in `Access-Control-Allow-Origin` and an arbitrary unlisted origin does not.

**Reasoning**: a wildcard origin combined with `allow_credentials=True` (needed for the `Authorization` header to be sent cross-origin in some configurations) is specifically what browsers refuse and what CORS misconfiguration checklists flag first — keeping this environment-driven means development stays convenient (one default origin) while production is forced to be explicit about exactly which frontend domain(s) may call the API.

**Status**: active.

---

## D29 — Issue authorization in Phase 4 is coarse-grained: owner-only for USER, all-issues for RESOLVER/ADMIN

**Context**: Phase 4 is the first phase with a real protected resource (`issues`), so resource-level authorization (D24's deferred item) has to be built now. But the two things a fully team-scoped model would need — routing that sets an issue's `current_team_id` (Phase 5) and resolver-workflow rules for what "my team's issues" even means operationally (Phase 7) — don't exist yet.

**Decision**: `issue_service._can_view_issue` and `list_issues_for_user` implement exactly two tiers: a `USER` may only see issues where `owner_id` matches their own id (enforced by forcing the query filter server-side — there is no request parameter that lets a `USER` ask for someone else's issues); a `RESOLVER` or `ADMIN` may see and status-transition *any* issue, with no team filter at all yet.

**Reasoning**: this is an honest, temporary simplification rather than a guess at team-scoping rules that don't have real requirements yet (no assignment mechanism exists to scope by). Building a fake team filter now, against data that's always empty (`current_team_id` is always NULL until Phase 5), would be speculative code with no way to verify it's even correct. Narrowing RESOLVER access to "issues assigned to my team" is explicit, tracked work for Phase 7 (DECISIONS.md D24), not something this phase pretends to have solved.

**Status**: active. Superseded by Phase 7's team-scoped resolver access.

---

## D30 — Status transition endpoint: RESOLVER/ADMIN only, and structurally cannot reach CLOSED

**Context**: `PATCH /issues/{id}/status` is the first place the D8 transition table (designed during the original architecture review) actually gets enforced in code, and needed a concrete authorization rule plus a decision about the RESOLVED→CLOSED edge specifically.

**Decision**: only `RESOLVER` or `ADMIN` may call this endpoint (`IssueAccessDeniedError` → 403 for a `USER`, including the issue's own owner). The transition table itself (`app/services/status_transition_rules.py`) gives `RESOLVED` an empty set of allowed next states — so even a resolver/admin cannot reach `CLOSED` through this endpoint; the attempt fails with the same "invalid transition" 400 as any other disallowed move.

**Reasoning**: matches D9's requirement that closing an issue requires the *submitting user's* explicit confirmation, not a resolver's own say-so — building a separate, dedicated confirmation endpoint now (before comments/resolution-recording exist) would mean either a stub or an incomplete flow. Blocking the transition entirely at the rule-table level, rather than adding an ad hoc role check only on that one target status, keeps the enforcement in the one place all transition rules already live, and makes the boundary self-documenting: `RESOLVED: frozenset()` in the table *is* the statement "nothing reaches CLOSED from here yet."

**Status**: active. Superseded by Phase 7's dedicated user-confirmation endpoint, which will be the only path to `CLOSED`.

---

## D31 — Concurrent status transitions: `SELECT ... FOR UPDATE` implementing D12

**Context**: D12 (from the original architecture review) specified the *policy* — never validate a transition against a client-supplied or stale status, always the real current database state — without yet having code to enforce it. Phase 4 is where that became real.

**Decision**: `issue_repository.get_issue_by_id_for_update` issues `SELECT ... FOR UPDATE`, so a second concurrent transition request on the same issue blocks at the database level until the first transaction commits or rolls back, then reads whatever state the first one actually left behind. `tests/test_issue_status_transitions.py::test_concurrent_transitions_are_serialized_against_real_current_state` verifies this with two real threads and two independent database connections against the same committed row (not the SAVEPOINT-isolated `db_session` fixture other tests use, which wouldn't give two threads a genuine race to serialize) — it asserts the invariant that holds regardless of which thread's lock wins the nondeterministic race, rather than a single hardcoded winner, since actually asserting a fixed winner would make the test flaky and would be asserting something false about how OS thread scheduling works.

**Reasoning**: this is the direct, tested implementation of the exact scenario D12 was written to prevent (resolver A and B both starting from `ASSIGNED`, only one of whose intended transitions can be legitimate once the other commits first) — and confirms the earlier architecture-review nuance about D12 was correct: whichever request is evaluated second legitimately sees the *new* current state and may succeed via a different, still-valid transition path than it originally assumed, which is correct behavior, not a bug.

**Status**: active.

---

## D32 — No AI-trigger wiring in Phase 4; nothing to stub

**Context**: the Phase 4 creation flow, as originally sketched during the architecture review (D3/D4), ends with "commit → return → trigger background AI analysis." Phase 4's actual boundary explicitly excludes AI.

**Decision**: `issue_service.create_issue` creates the issue, writes the `SYSTEM_CREATE` status-history row, commits, and returns — nothing else. There is no background task call, no stub function, no placeholder AI trigger anywhere in the Phase 4 code. `issue.ai_analysis_status` starts at `PENDING` purely because that's the column's default value (set in Phase 2), not because anything actively initiated analysis.

**Reasoning**: the project rules explicitly forbid "TODO-driven fake functionality." A stub `trigger_ai_analysis()` function that does nothing (or that always leaves the issue at `PENDING` forever) would be exactly that - dead weight Phase 5 would have to find and replace rather than a real extension point. The actual `BackgroundTasks.add_task(...)` call is added in Phase 5's `create_issue`, at the same time the `AIProvider` it calls is built - there's nothing correct to write here before that exists.

**Status**: active. Superseded by Phase 5.
