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

**Status**: superseded by D33-D39 below, which implement exactly this.

---

## D33 — `ai_analysis_results` is built now, fulfilling D19's deferral

**Context**: D19 (Phase 2) deliberately deferred this append-only AI-suggestion-history table, saying it "belongs with AI classification itself" — which, under the phase numbering active when D19 was written, was labeled "Phase 7." The project's phase plan was later renumbered (AI classification is now Phase 5), but the underlying intent - build this table when AI classification is actually implemented, not before - is unchanged.

**Decision**: `ai_analysis_results` is added via its own migration (`07be6efb521f_add_ai_analysis_results`), append-only, one row per classification attempt (including manual reanalysis), with a `(issue_id, attempt_number)` unique constraint. It stores both the raw AI output (`raw_category`, `raw_sub_category`, `raw_priority`, even on a `FAILED` row - what the AI actually said, preserved for debugging/audit) and the validated, matched result (`matched_category_id`, `matched_sub_category_id`, `matched_priority` - only populated when validation succeeded). The composite-FK pattern from D17 is reused for `(matched_category_id, matched_sub_category_id)`, for the same reason: an invalid category/sub-category pairing must be impossible to store, even here.

**Reasoning**: this is the correct moment to build it - AI classification exists now, so there's a real pipeline to attach history to and real behavior to verify against, rather than a speculative schema guessed at during Phase 2. Keeping both the raw and matched values means an admin (or a future debugging session) can always answer "what did the AI actually say, and why did we reject/accept it" from durable data alone.

**Status**: active.

---

## D34 — `AIProvider`: structural validation only, OpenAI-compatible via configurable base URL

**Context**: the provider must be swappable (no code path should be locked to one vendor), and needs to work with whichever OpenAI-compatible endpoint this deployment is configured for - in practice, verified live against Google's Gemini OpenAI-compatibility layer during this phase's manual testing, not just the real OpenAI API.

**Decision**: `OpenAICompatibleProvider` wraps the `openai` Python SDK's `OpenAI` client with a configurable `base_url` (`OPENAI_BASE_URL`, unset = real OpenAI). `classify()` sends a system prompt instructing the model to return one JSON object with exactly five keys, parses the response, and validates only its *shape* against the `AISuggestion` Pydantic model (right fields, right types) - it has no database access and does not know what a "real" category is in this deployment. A network/timeout/API error raises `AIProviderError`; a response that doesn't parse into that shape raises `AIResponseFormatError`. Neither exception, nor a successful structural parse, implies the *content* is trustworthy - that's `ai_validation.py`'s job (D35), one layer up.

**Reasoning**: this is the concrete implementation of D4/D10's "small, understandable `AIProvider` abstraction, no framework." Splitting structural validation (this module) from semantic validation (D35) keeps the provider genuinely swappable - a new provider only has to produce the same five JSON keys, not know anything about this deployment's category taxonomy. Verified live: a real call to Gemini succeeded and returned a structurally valid suggestion whose *category value* ("Network," a sub-category in this deployment's taxonomy, not a top-level category) was then correctly rejected by the semantic layer - concrete proof the two-layer split does its job, not just a claim.

**Status**: active.

---

## D35 — Semantic AI validation: explicit normalization rules, no silent coercion

**Context**: D5 requires the backend to never blindly trust the LLM's classification, while still allowing "explicit normalization" where it's genuinely safe.

**Decision**: `validate_ai_suggestion` (`app/services/ai_validation.py`) applies exactly two explicit normalizations - case-insensitive matching for category/sub-category names, and case-insensitive matching for the priority string against the `IssuePriority` enum - and nothing beyond that. Three outcomes: (1) the category doesn't match any real, active category by name → hard failure (`AIValidationError`), the whole analysis is `FAILED`; (2) the category matches but the sub-category doesn't match anything under it → the sub-category is silently dropped (not a failure), since a correct broader classification is still useful even without the finer one; (3) the priority string doesn't match one of the four real values → hard failure, since priority feeds SLA lookup and escalation and a silent default would be worse than an honest failure.

**Reasoning**: each of these three outcomes was a deliberate choice about where "helpful leniency" stops and "fabrication" begins. Category is the load-bearing field (it drives routing and SLA), so it gets zero tolerance beyond case-folding. Sub-category is optional supplementary detail, so losing it (not the whole classification) on a mismatch is the more useful failure mode. Priority has exactly four valid values with no reasonable "closest guess," so any value outside that set is rejected outright rather than mapped to a guessed default.

**Status**: active.

---

## D36 — Deterministic priority escalation uses whole-word matching, not substring containment

**Context**: `RoutingService.determine_final_priority` escalates the AI's suggested priority to at least `HIGH` when the issue text contains certain keywords ("outage," "down," etc.) - a deterministic backend rule that can override the AI's own judgment, per D4.

**Decision**: keyword matching uses `\bkeyword\b` regex word-boundary matching, not `keyword in text` substring containment.

**Reasoning**: this fixes a real bug caught by this phase's own test suite: a naive substring check made "dropdown," "showdown," and "downtown" all incorrectly trip the "down" keyword and escalate unrelated issues to `HIGH` priority. The regression is now a permanent test (`tests/test_routing_service.py::test_keyword_matching_is_whole_word_not_substring`) alongside the positive case, so this class of false positive can't silently return.

**Status**: active.

---

## D37 — Background-task testability: injectable `provider` and `session_factory`

**Context**: `run_ai_analysis` must, in production, call the real configured `AIProvider` and open its own session via the real `SessionLocal` (D4). Tests must do neither - a real network call in the test suite would be slow, flaky, potentially costly, and non-deterministic; and the real `SessionLocal` is bound to the *dev* database (`DATABASE_URL`), not the test suite's isolated `resolve_test` transaction, so using it directly would silently no-op against the wrong database.

**Decision**: `run_ai_analysis(issue_id, provider=None, session_factory=None)` - both parameters default to the real production values (`get_default_provider()`, `SessionLocal`) when omitted, so the call site used by the actual API route (`background_tasks.add_task(run_ai_analysis, issue.id)`) is unchanged and unaware tests exist. Tests inject a `FakeAIProvider` (`tests/fake_ai_provider.py`) and a `session_factory` bound to the test transaction (`ai_session_factory` fixture in `conftest.py`, itself built on a new `db_connection` fixture exposing the raw connection so a second, independently-closeable `Session` can share the same test transaction without tearing down the one other fixtures still need).

**Reasoning**: dependency injection with production-safe defaults is the standard way to make a side-effecting entry point testable without changing its production call signature or behavior. The alternative - monkeypatching module-level globals in tests - was rejected as fragile and implicit; explicit parameters make what's under test's control visible directly in the test's own code.

**Status**: active.

---

## D38 — Manual reanalysis: access control, cooldown, and the OPEN-only routing scope rule, now implemented

**Context**: D13 (from the original architecture review) specified the *policy* for `POST /issues/{id}/reanalyze` without implementing it. This phase is where that became real code.

**Decision**: `request_reanalysis` (`app/services/ai_analysis_service.py`) enforces, in order: (1) caller must be `RESOLVER` or `ADMIN` (`ReanalyzeAccessDeniedError` → 403); (2) the issue must exist (404); (3) `ai_analysis_status` must not already be `PROCESSING` (`ReanalyzeInProgressError` → 409 - no duplicate concurrent analysis jobs); (4) the most recent `ai_analysis_results.created_at` must be older than `AI_REANALYZE_COOLDOWN_SECONDS` (default 120s) ago (`ReanalyzeCooldownError` → 429 with a `Retry-After` header). Only then does it flip `ai_analysis_status` to `PENDING` and return, for the route handler to schedule the same `run_ai_analysis` background task used by issue creation. Inside that task, `route_issue` (D31's guard) only actually re-routes the issue if it's still `OPEN`; on an issue that's already progressed further, reanalysis records a fresh `ai_analysis_results` row (a new attempt number, prior attempts untouched) without touching the issue's current category/team/priority/status at all - verified end to end by `test_reanalyze_on_already_routed_issue_does_not_re_route`.

**Reasoning**: this is the concrete implementation of D13's promise that reanalysis is a genuine recovery mechanism (for D14's stuck-`PROCESSING`/crashed-task scenario) without ever letting the AI silently override a human's subsequent work on a routed issue.

**Status**: active.

---

## D39 — Dev-only reference-data seed script

**Context**: routing cannot do anything useful against empty `categories`/`teams`/`routing_rules`/`sla_rules` tables (Phase 2 deliberately left them empty - D16), but there is no admin-facing way to populate them yet (that's Phase 8). Without *something*, this phase's own manual verification - and any future local development - would have nothing to route against.

**Decision**: `backend/scripts/seed_dev_reference_data.py`, run manually (`python -m scripts.seed_dev_reference_data`), never imported by any application or migration code. It refuses to run unless `ENVIRONMENT=development`, and is idempotent (checks for existing rows by name before inserting, so running it twice is harmless).

**Reasoning**: this is exactly the "development-only seed mechanism... clearly isolated in an explicit development-only script" the project rules anticipate for cases where real configuration is genuinely required to exercise the system, as distinct from fake business data (users, issues), which this script never touches.

**Status**: active. Superseded once Phase 8 adds a real admin-facing management UI for this configuration.

---

## D40 — SLA engine: pause/resume wired into the transition endpoint, pure DB-reconstructable computation

**Context**: the SLA schema (`sla_records`, `sla_pause_intervals`, the exclusion constraint) was built in Phase 2 (D19), and Phase 5's `RoutingService` already creates the initial `sla_records` row with fixed deadlines when routing succeeds. What was still missing: actually opening/closing pause windows when an issue enters/leaves `WAITING_FOR_USER`, and computing effective elapsed time, at-risk state, and breach state from that data.

**Decision**: `app/services/sla_service.py` adds two write operations and one pure read computation:
- `open_pause`/`close_pause` are called from inside `issue_service.transition_status`, in the same row-locked transaction as the status change itself - entering `WAITING_FOR_USER` opens a pause, leaving it (`WAITING_FOR_USER → IN_PROGRESS`) closes it and folds the duration into `sla_records.accumulated_pause_seconds`. Nothing about *when* to pause/resume lives outside this one call site tied to the state machine.
- `compute_sla_status(sla_record, now=...)` is a pure function: given an `SLARecord` with its `pause_intervals` loaded, it returns effective elapsed time, remaining time, and at-risk/breached flags for both the first-response and resolution targets, independently of each other. "At risk" is `remaining_time <= SLA_AT_RISK_THRESHOLD_FRACTION * original_duration` (default 20%) - a fixed, documented, configurable fraction, not a guess. The function takes no dependency on wall-clock time except through its `now` parameter, and no dependency on anything held in Python process memory - it was tested (`test_reconstructs_correctly_from_a_freshly_loaded_record_simulating_a_restart`) by computing against a record, discarding all in-memory state (`session.expire_all()`), reloading it fresh, and confirming an identical result.
- `IssuePublic.sla` (via a new `build_issue_public()` helper used by every issue-returning endpoint) exposes this computed status over the API - `first_response_deadline_at`, `resolution_deadline_at`, `effective_elapsed_seconds`, `accumulated_pause_seconds`, `is_paused`, and the four at-risk/breached booleans.

**Reasoning**: this directly satisfies the Phase 6 auditability requirement ("a future administrator must be able to answer 'why was this issue considered breached' from persisted data") - every number `compute_sla_status` produces is derived from columns that exist in the database, nothing is cached or computed once and forgotten. Wiring pause/resume into the same transaction as the triggering status change (rather than as a separate step) means the two can never drift apart, the same principle already established for AI routing (D40 continues D19's "no event sourcing, a small durable relational design is enough" stance) - the database's exclusion constraint from D19 remains the final backstop, and this phase's own concurrency test (`test_concurrent_waiting_for_user_entry_opens_exactly_one_pause`, real threads/connections, not the SAVEPOINT-isolated fixture) confirms the row lock inherited from D12/D31 prevents a double-open before that constraint would even need to fire.

**Status**: active.

---

## D41 — Phase 7: team-scoped resolver access, append-only assignment, atomic auto-resume, and the confirm/reject resolution flow

**Context**: four related pieces of D24's "deferred until issue APIs exist" plan came due together: narrowing resolver access from Phase 4's coarse "any resolver, any issue" to genuine team scoping; assignment/reassignment with append-only history (D7); comments; and the D9/D11 rules that had only been specified, not built, since the original architecture review.

**Decision**:
- **Team-scoped access**: `issue_service.can_access_issue` (made public, replacing the private `_can_view_issue` and now also used by `transition_status` and `comment_service`) is the one place this is decided: `ADMIN` → always; `RESOLVER` → `issue.current_team_id is None or issue.current_team_id == user.team_id`; `USER` → `issue.owner_id == user.id`. An unassigned issue stays visible to every resolver (so it can be noticed and picked up - "not silently dropped"); an issue already routed to a specific team is invisible to every other team's resolvers, including one with no team at all. `list_issues_for_user`/`issue_repository.list_issues` mirror the identical rule (`team_id IS NULL OR team_id = :mine`) so a resolver's list and what they can individually open never disagree.
- **Assignment**: `assignment_service.update_assignment` - an `ADMIN` may set `team_id` and/or `resolver_id` to anything (with one validation: an assigned resolver must actually belong to the target team, checked explicitly rather than left to the FK alone, since the FK can't express "belongs to this specific team"); a `RESOLVER` may only self-assign (`resolver_id` must equal their own id, `team_id` cannot change) on an issue already on their own team. Every call inserts a new `issue_assignments` row; `issues.current_team_id`/`current_resolver_id` are updated in the same transaction. Assignment is deliberately independent of status - reassigning an issue never itself changes `status`.
- **Comments**: `POST/GET /issues/{id}/comments`, access-gated by the same `can_access_issue`. The CRITICAL SPECIAL RULE (Phase 7 spec, D11): `comment_service.add_comment` loads the issue under `SELECT ... FOR UPDATE` (the same lock every other mutation uses), inserts the comment, and - only if the issue is currently `WAITING_FOR_USER` *and* the commenter is the issue's own owner - atomically also transitions it to `IN_PROGRESS`, closes the SLA pause (reusing `sla_service.close_pause`, exactly as anticipated when that function was built in D40), and writes an `issue_status_history` row with `trigger=AUTO_USER_REPLY`. A resolver, admin, or anyone else commenting never triggers this, checked explicitly by comparing `author.id == issue.owner_id`, not by role.
- **Confirm/reject resolution**: `POST /issues/{id}/resolution/confirm` and `.../reject`, both owner-only (`issue.owner_id != current_user.id` → 403, not even an `ADMIN` may call these - no silent override exists, matching the original architecture review's explicit "out of MVP scope" call on admin override). Confirm requires `status == RESOLVED` and moves to `CLOSED`, setting `closed_at`. Reject requires the same precondition and returns the issue to `IN_PROGRESS` (an active state a resolver can act on again), accepting an optional note. Both are separate from `status_transition_rules.ALLOWED_TRANSITIONS` (which still has nothing outgoing from `RESOLVED` - D30) - they're a distinct authority path with its own owner-only check, not a role-based one, so folding them into the generic table would have been the wrong shape for the rule.

**Reasoning**: each of these four pieces reuses machinery already built rather than inventing new patterns - the row lock from D12/D31, the SLA pause functions from D40, the same `can_access_issue` predicate for viewing/transitioning/commenting. That reuse is itself the argument for correctness: there's exactly one definition of "can this person touch this issue," so it can't drift between the four surfaces that need to ask the question.

**Status**: active.

---

## D42 — Admin management endpoints: the real replacement for manual database inserts

**Context**: every prior phase's manual/live verification had to insert a RESOLVER or ADMIN user directly into the database with raw SQL, because no code path could create one (D23: public registration always creates `USER`). That gap was explicitly called out as a known limitation in the README after Phases 3, 4, 5, 6, and 7. Phase 8 is where it finally closes.

**Decision**: `app/api/routes/admin.py`, entirely gated by `require_admin` at the router level (one `dependencies=[Depends(require_admin)]` on the `APIRouter`, not repeated per endpoint). CRUD for `teams`, `categories`/`sub_categories`, `routing_rules`, `sla_rules`, and `PATCH /admin/users/{id}` for role/team/`is_active`. Three rules enforced in `admin_service.py`, not left to chance:
- **No hard deletes anywhere** - every "remove" is `is_active=False`, consistent with D15. There is no `DELETE` verb on any admin endpoint.
- **Role changes stay consistent with D18's team-per-resolver invariant**: promoting a user to `RESOLVER` without a team_id (new or already set) is rejected (`ValidationError` → 400); demoting a `RESOLVER` away from that role clears their `team_id`, since a team assignment is meaningless for a `USER` or `ADMIN`. This is the "real provisioning entry point" D18 said the app-layer check belonged at - it didn't exist until now.
- **Role strings are validated against the real role set** (`ALL_ROLE_NAMES` from D20), not accepted as arbitrary text - `{"role": "SUPERUSER"}` is a 400, not a silently-broken foreign key lookup.

**Reasoning**: this is the first phase where "grant someone elevated access" has an actual, tested, audited code path instead of a documented workaround. It was verified end to end with real HTTP requests (not just unit tests): an ADMIN promotes a `USER` to `RESOLVER` with a team, the promoted user's next login and every subsequent request reflects the new role immediately (D21's fresh-reload guarantee applies here too - no re-issued token needed), the promoted user gets exactly `RESOLVER` access (not `ADMIN`), and a plain `USER` attempting the same promotion endpoint - on themselves or on someone else - is rejected with 403 by the same `require_admin` dependency every other admin surface uses. No new authorization pattern was invented for this; it's D24's role-based RBAC dependency, applied to one more router.

**Status**: active.

---

## D43 — Dashboard metrics: real queries only, at-risk as a list not just a count, admin-only team workload

**Context**: the Phase 8 spec is explicit that every dashboard number must come from an actual database query - no placeholder figures - and that "SLA at risk" should be a prioritized list a resolver can act on, not only a tile showing a number.

**Decision**: `dashboard_service.py` exposes three real queries, all scoped by the identical role rule as issue listing (`can_access_issue`'s scope, D41) so a dashboard never shows a USER, RESOLVER, or ADMIN anything they couldn't also see by opening the issue directly:
- `get_summary`: open-request count, high-priority count, SLA-at-risk count (via `compute_sla_status`, same function D40 built - no second definition of "at risk"), and issues resolved today (`resolved_at >= today's UTC midnight`).
- `get_at_risk_issues`: the actual issues behind that count, sorted by resolution deadline, sharing its scoping helper with `get_summary` (`_open_issues_with_sla_in_scope`) so the tile and the list can never disagree about which issues qualify.
- `get_breakdown`: status counts and priority counts (both scoped), AI-analysis failure count, and - ADMIN only - team workload (a `GROUP BY` over currently-open issues per team). Team workload is admin-only because it inherently spans every team; a resolver's own dashboard already shows their team's issues directly.

**Reasoning**: computing "at risk" by iterating open issues with an SLA record in Python (rather than a single SQL aggregate) is a deliberate, documented tradeoff - the underlying computation (D40's pause-aware effective-elapsed math) isn't expressible as a plain column comparison, and at this project's real scale (a portfolio-sized deployment, not enterprise issue volume) the cost is negligible. It's flagged in the code as a scale consideration precisely so it isn't mistaken for something that would stay cheap at very large issue counts.

**Status**: active.
