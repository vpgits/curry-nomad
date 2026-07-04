# Nora — Agentic-Memory Multi-Tenancy Audit

**Scope:** read-only assessment of whether Nora's agentic-memory backend (LangGraph checkpointer +
BaseStore, served by Aegra) is ready for multi-tenant use. No code, migrations, or config were
modified. App-layer citations were read directly; Aegra-internal citations are from the installed
`aegra-api` v0.9.22 package under `.venv/lib/python3.12/site-packages/`.

**One-line answer:** Nora is **single-user-per-account, single-org** at best — and *only if* an
operator opts into `AUTH_TYPE=custom`. As currently deployed (`AUTH_TYPE=noop`) every request is the
same anonymous identity, so there is **no isolation at all**. There is no org/tenant tier anywhere
(no column, no RLS), and the app's long-term "memory" is a **global shared read-only knowledge base**,
not per-user memory. `langmem` is not installed.

---

## 0. Versions (from `uv.lock` / `pyproject.toml` / dist-info)

| Package | Version | Notes |
|---|---|---|
| `langgraph` | **1.2.6** | `pyproject.toml:11` pins `>=1.0,<2.0` |
| `langgraph-checkpoint` | 4.1.1 | transitive |
| `langgraph-checkpoint-postgres` | **3.1.0** | Postgres checkpointer + `AsyncPostgresStore` (pulled in by Aegra) |
| `langgraph-sdk` | 0.4.2 | provides the `Auth` primitives + Store client |
| `langchain-core` | 1.4.8 | — |
| `aegra-api` / `aegra-cli` | **0.9.22** | `pyproject.toml:52-54` (`aegra = ["aegra-cli>=0.9.22"]`) |
| `langmem` | **NOT INSTALLED** | 0 hits in `uv.lock`, absent from `.venv`, no usage in `apps/` |
| `pgvector` (Python) | **NOT INSTALLED** | pgvector is the *Postgres extension* only — DB image `pgvector/pgvector:pg18` (`docker-compose.yml:24`); LangGraph's store runs `CREATE EXTENSION vector` on demand |

The stack-context guess that Nora "likely uses LangMem" is **false** — there is no memory
extraction/consolidation library and no agent-authored memory anywhere.

---

## 1. Identity & tenancy model — **verdict: single-org, per-user (only when custom auth is on)**

### There is no org/tenant concept anywhere in the app
Grep of `apps/nora/src` for `tenant`, `org_id`, `organization`, `account_id` → **zero matches**.
`Settings` has no tenant/org field (`apps/nora/src/nora/config.py:39-140`). The Next.js app has no
org/tenant either (audited separately) — only single-identity UI copy.

### The only identity unit is the individual user (`sub`/`email`)
`apps/nora/src/nora/auth.py:52` — the identity extracted from the verified JWT:
```python
identity = payload.get("sub") or payload.get("email")
```
No org/tenant claim is read. Threads/runs/store are keyed on this flat `identity` at the Aegra layer
(§2, §5).

### `Context.user_id` exists but is dead code — it does **not** namespace anything
`apps/nora/src/nora/schemas.py:232-234`:
```python
class Context:
    user_id: str = "arun"  # single demo user; namespaces the store
    model: str | None = None  # optional per-run model override
```
The comment claims it "namespaces the store," but `user_id` is **never read anywhere** — grep of the
entire `nora` package for `user_id` returns only this declaration. No `Context(...)` is ever
instantiated (`grep "Context("` → 0). The store is namespaced by fixed global constants instead
(§3). So the per-user namespacing the design gestures at is **not implemented**.

### Verdict
**Single-user-per-account, single-org.** Under `AUTH_TYPE=custom`, Aegra isolates *threads* and the
*REST store* per operator (platform-enforced — §2/§5), which is genuine per-user isolation within one
shared pool. But there is **no organization/tenant tier** (no column, no RLS, no grouping of users),
so it is **not** "single-org-many-users with org boundaries" and **not** genuine multi-org
multi-tenant. And the app's own agentic memory is global, not per-user (§3). As deployed today
(`AUTH_TYPE=noop`, see §2) it collapses to a single shared `anonymous` identity — effectively
zero-tenant.

---

## 2. Aegra auth configuration

### `AUTH_TYPE` defaults to `noop`; it is `noop` right now
`docker-compose.yml:62`:
```yaml
AUTH_TYPE: ${AUTH_TYPE:-noop}
```
`.env.example:75` documents `AUTH_TYPE=noop` as the keyless default. **The live `.env` has
`AUTH_TYPE=noop` explicitly set** (line 70) while `NORA_WORKSPACE_ENABLED=true` (line 62) — so the
running posture has the Google-account agent enabled but **no operator identity at all**.

### There IS an `@auth.authenticate` handler — verifying a real token
`apps/nora/src/nora/auth.py:64-92`. It validates the **NextAuth-minted HS256 session JWT** from the
`Authorization: Bearer` header, with `NEXTAUTH_SECRET` as the symmetric key:
```python
@auth.authenticate
async def authenticate(headers) -> dict:
    if os.environ.get("AUTH_TYPE", "noop").lower() != "custom":
        return {"identity": "anonymous", "display_name": "", "is_authenticated": True}  # ← noop path
    ...
    return verify_session_token(token, secret)
```
`verify_session_token` (`auth.py:43-61`) restricts algorithms to `HS256` (no alg-confusion),
extracts `identity = sub or email`, `display_name`, and an optional `google_access_token` claim.
**The tenant/identity is derived from a VERIFIED token claim** (signature-checked JWT) — good — but
**only the individual `sub`/`email`; no org/tenant claim exists.** Note the `noop` branch returns a
fixed `"anonymous"` identity for *every* caller.

### There are NO `@auth.on` authorization handlers — anywhere
`auth.py` is 92 lines and contains only `@auth.authenticate`. Grep of `apps/nora/src` + `apps/web`
for `auth.on` / `add_owner` / `filters` → **zero matches**. So the app registers **no**
owner-stamping-on-create and **no** read/search filter dict for threads, assistants, crons, or store.

The LangGraph SDK itself documents that per-user store isolation is what an `@auth.on.store` handler
provides (`.venv/.../langgraph_sdk/auth/__init__.py:87-89, 195-213`, "scope store operations by
rewriting the namespace to include the user's identity") — the app implements none of these.

### Critical: is the long-term STORE covered? — **Yes, but by Aegra's hard-coded logic, not by this app**
This is the pivotal finding. In Aegra 0.9.22, authorization handlers are **additive**, not the thing
that provides isolation. Every `/store` REST route rewrites the namespace under the authenticated
identity regardless of whether an `@auth.on.store` handler exists:

`.venv/.../aegra_api/api/store.py:236-249`:
```python
def apply_user_namespace_scoping(user_id: str, namespace: list[str]) -> list[str]:
    """All store operations are scoped to the authenticated user's namespace.
    Users can only access namespaces under ["users", <their_user_id>]."""
    if not namespace:
        return ["users", user_id]
    if namespace[0] == "users" and len(namespace) >= 2 and namespace[1] == user_id:
        return namespace
    return ["users", user_id] + namespace
```
Called on every put/get/delete/search/list (`store.py:47, 81, 130, 163, 210`). With no
`@auth.on.store` handler, `handle_event()` returns `None` = allow (`aegra_api/core/auth_handlers.py:108-122`),
and the scoping fires anyway.

**Two caveats that matter for Nora specifically:**
1. **`noop` → shared pool.** Under `AUTH_TYPE=noop`, `identity="anonymous"`, so
   `apply_user_namespace_scoping("anonymous", …)` funnels **all** callers into `["users","anonymous"]`.
   Aegra's own code warns about this (`aegra_api/core/auth_middleware.py:238` "no tenant isolation is
   enforced"). This is the current posture.
2. **In-graph store access bypasses the scoping** — see §3. The REST scoping protects direct Store
   API clients; it does **not** protect reads/writes the graph makes via `runtime.store`.

---

## 3. Long-term memory store wiring — **a global, shared, read-only knowledge base**

### Instantiation: `InMemoryStore` (CLI) / Postgres+pgvector (platform)
CLI path (`apps/nora/src/nora/memory.py:38-47`):
```python
def build_store(settings: Settings) -> InMemoryStore:
    return InMemoryStore(index={
        "embed": init_embeddings(settings.embedding_model),
        "dims": settings.embedding_dims,          # 1536
        "fields": ["text", "$"],
    })
```
Platform path (`aegra.json:8-15`) — Aegra injects an `AsyncPostgresStore` with the same index:
```json
"store": { "index": { "embed": "openai:text-embedding-3-small", "dims": 1536, "fields": ["text", "$"] } }
```
`make_graph()` (`orchestrator.py:653-664`) compiles **without** a store so the platform injects it.

### Every `store.put/get/search/delete` call — the namespace root is a fixed literal, not the user
There are only **three** store call sites in the whole app, and **none** is a per-user write:

| Call | `path:line` | Namespace tuple | Root |
|---|---|---|---|
| seed `put` | `memory.py:118` | `("curry_nomad","brand")` / `("curry_nomad","definitions")` | literal `"curry_nomad"` |
| brand `search` (marketing) | `marketing/nodes.py:104` | `BRAND = ("curry_nomad","brand")` | literal |
| definitions `search` (analytics) | `analytics/graph.py:173` | `DEFINITIONS = ("curry_nomad","definitions")` | literal |

`apps/nora/src/nora/memory.py:34-35`:
```python
BRAND = ("curry_nomad", "brand")
DEFINITIONS = ("curry_nomad", "definitions")
```
`apps/nora/src/nora/analytics/graph.py:170-174`:
```python
runtime_store = getattr(runtime, "store", None)
if runtime_store is not None:
    query = _last_user_text(state["messages"]) or "metric definitions"
    items = runtime_store.search(DEFINITIONS, query=query, limit=3)   # ← global namespace, no user
```
**The namespace root is neither the tenant/user nor `thread_id` — it is a hardcoded brand string.**
This is not the "thread_id-as-root" antipattern; it is the *global-shared* case. All reads target the
same two namespaces for everyone. There are **no per-user or per-thread memory writes** — the store
holds only the seeded brand voice + metric definitions and is read-only at runtime.

### The seed-vs-read namespace mismatch on the platform path (flag for verification)
The platform seed script writes over the **REST** Store API, which applies the §2 scoping; the graph
reads via **`runtime.store`**, the **raw** unscoped store. These namespaces likely do **not align**:
- `apps/nora/scripts/seed_store.py:32` seeds `("curry_nomad","brand")` via `client.store.put_item(...)`,
  which Aegra rewrites to `["users",<identity>,"curry_nomad","brand"]` (under `noop`,
  `["users","anonymous","curry_nomad","brand"]`).
- `analytics/graph.py:173` reads the literal `("curry_nomad","definitions")` on the raw store
  (Aegra injects the raw store into the graph — `aegra_api/services/langgraph_service.py:354`
  `store = db_manager.get_store()`, no scoping wrapper).

So on Aegra the agent's in-graph search would look at `curry_nomad.*` while the seed landed under
`users.*.curry_nomad.*`. **This suggests the seeded memory is not actually found on the platform
path** (a functional gap, and evidence the per-user store path was never exercised end-to-end).
*Could not fully confirm without a live instance — flagged for verification.*

### LangMem
**Not used.** No `create_manage_memory_tool`, `create_search_memory_tool`, or memory manager anywhere
(grep → 0; package not installed). There is no memory extraction/consolidation and therefore no
namespacing to propagate tenant/user into.

---

## 4. Checkpointer / thread state

### Checkpointer
- CLI: `InMemorySaver` (`memory.py:63-65`).
- Platform: Aegra injects `AsyncPostgresSaver` (created via `.setup()` in
  `aegra_api/core/database.py:73`).

### Thread state is keyed by `thread_id` only; no owner/tenant on the checkpoint
The checkpoint tables (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`) are created by LangGraph
itself (`langgraph/checkpoint/postgres/base.py:47-75`) with `PRIMARY KEY (thread_id, checkpoint_ns,
checkpoint_id)` and **no `user_id`/`tenant_id`/`owner` column**. Ownership is enforced *only* at
Aegra's REST layer via the separate `thread.user_id` row (§5), never at the checkpoint table. So a
checkpoint is reachable by anyone who can present its `thread_id` at a layer that doesn't re-check the
owning row.

The app writes no owner into thread metadata itself; Aegra stamps `metadata["owner"] = user.identity`
and `thread.user_id = user.identity` on creation (`aegra_api/api/threads.py:198-210`). The CLI uses a
constant `THREAD_ID = "demo-1"` (`app.py:36`) — single-user by construction.

### Secret-at-rest note
The Google access token is passed per-run in `config.configurable.google_access_token`
(`orchestrator.py:556`), which the checkpointer persists. The code's own `# TODO(prod)`
(`orchestrator.py:557-559`) acknowledges the token "rides in run config, which the checkpointer
persists" — a short-lived OAuth token lands in per-thread checkpoint storage.

---

## 5. Database & isolation

### Schema
- **Aegra metadata tables** (Alembic, `aegra_api/alembic/versions/`) carry a flat **`user_id text`**:
  `assistant.user_id NOT NULL` (`20250817172544_initial_schema.py:48`), `thread.user_id` (`:92`),
  `runs.user_id` (`:129`), `crons.user_id` (`20260413201423_add_crons_table.py:28`). `thread` also
  has `metadata_json jsonb` holding an `"owner"` key.
- **Store table** (LangGraph, `langgraph/store/postgres/base.py:64-72`): `store(prefix, key, value,
  …)` PK `(prefix, key)` + `store_vectors(...)`. **Only isolation dimension is `prefix`** (the
  dot-joined namespace).
- **Checkpoint tables**: keyed on `thread_id` (see §4).

**There is NO `tenant_id` / `org_id` / `owner` column** on the store or checkpoint tables, and the
only isolation column on Aegra's own tables is `user_id` — a single flat user, no tenant grouping.

### RLS / schema-per-tenant / db-per-tenant
**None.** Grep across `aegra_api` for `ROW LEVEL SECURITY` / `CREATE POLICY` / `ENABLE RLS` /
`CREATE SCHEMA` / `search_path` matched only prose comments — **zero DDL**. Isolation is purely
application-level (`WHERE user_id = identity` for threads/runs; namespace-prefix rewrite for the REST
store). Single pooled schema, single DB (`docker-compose.yml:56` one `aegra` database/user).

Threads/assistants/runs ARE filtered per identity at the REST layer — e.g.
`aegra_api/api/threads.py:267` `.where(ThreadORM.thread_id==id, ThreadORM.user_id==user.identity)`;
runs stamped and filtered at `run_preparation.py:264` / `runs.py:162,199,…`. `create_run_config`
force-overwrites `configurable.thread_id`/`run_id` server-side and strips client-pinned checkpoint
keys (`langgraph_service.py:719-748`), so a client body can't redirect execution to another user's
thread. **This is the backstop** that makes the frontend's user-unscoped thread search (§7) safe —
*under custom auth*.

### Connection pooler
No bundled PgBouncer/pgpool. The code is written to be **transaction-pooler-safe**:
`aegra_api/core/database.py:37-44` sets `prepared_statement_cache_size: 0` (`# PgBouncer
compatibility`) and `:46-62` a `psycopg_pool.AsyncConnectionPool` with `prepare_threshold: None`.
**No `SET LOCAL` / `SET SESSION` / session-GUC usage anywhere** — which also means **no
session-variable-based tenant scoping** (no `SET app.current_user` + RLS pattern). Redis is optional
(`settings.py:340` `REDIS_BROKER_ENABLED=False` default) and is a job queue / SSE bus, not a DB pooler.

---

## 6. Async / worker write path

Aegra's worker carries the authenticated user **explicitly** and cannot normally write without one,
but it is **trust-on-first-write** (no re-verification):
- The full user object is serialized into the run row: `RunJob.user` →
  `execution_params.user` JSONB (`aegra_api/models/run_job.py:67, 74-87`).
- **Redis carries only the `run_id`** (`services/worker_executor.py:61-63`); the worker rebuilds the
  job from Postgres (`worker_executor.py:402` `RunJob.from_run_orm(...)` →
  `User.model_validate(params["user"])`) and executes under `with_auth_ctx(job.user, …)`
  (`services/run_executor.py:137-146`), re-injecting `configurable.user_id` + `langgraph_auth_user`
  (`langgraph_service.py:661-686`).

**Where a write could land without a fresh verification:**
1. The worker **replays the stored `user` without re-authenticating** — the identity is frozen at
   submit time. Server-written rows are trustworthy, but there is no signature on the persisted user.
2. **Cron firing synthesizes a `User` from a stored column**
   (`services/cron_scheduler.py:189-193` `User(identity=cron.user_id, is_authenticated=True)`), gated
   only by `_validate_cron_user()` which **by default returns `bool(user_id)`** — accepts any
   non-empty id (`cron_scheduler.py:71-80`); operators must monkey-patch it for revocation.
3. **Most important for Nora:** even with `configurable.user_id` populated, **in-graph store writes
   are not forced into that user's namespace** (§3). The app currently makes no such writes, but if it
   adds per-user/agentic memory later, the async path provides the *identity* but not the
   *namespacing* — that is left to graph code that does not exist yet.

---

## 7. Frontend → backend identity

*(Audited in `apps/web`; build artifacts excluded.)*
- **Token minting:** `apps/web/auth.ts:27-42` — the NextAuth `session` callback mints an **HS256**
  JWT with `SignJWT({ sub, email, name })`, 1h expiry, signed with `AUTH_SECRET` (which **must equal**
  the backend `NEXTAUTH_SECRET`). **No org/tenant claim; no `google_access_token` claim** (kept
  separate).
- **Attachment:** attached as `Authorization: Bearer <aegraToken>` via `defaultHeaders` on both the
  `useStream` client (`apps/web/providers/Stream.tsx:34-43`) and the raw SDK client
  (`apps/web/lib/auth-headers.ts:9`). Omitted when signed out (keyless `noop` path).
- **Thread IDs are client-chosen for *loading*.** `thread_id` comes from the URL query string
  (`Stream.tsx:30` `useQueryState("threadId")`); new threads are server-minted (`onThreadId`), but an
  existing conversation loads **whatever `?threadId=` the client supplies**. There is no `middleware.ts`
  and no client-side ownership check.
- **Thread list is NOT user-scoped on the client:** `apps/web/providers/Thread.tsx:40-41`
  `client.threads.search({ metadata: { graph_id: ASSISTANT_ID }, limit: 100 })` — filtered by
  `graph_id: "nora"` **only**, no user predicate.
- **Net:** a client can *ask* for any `thread_id` and lists threads with no user filter — **the only
  thing preventing cross-user access is Aegra's server-side `WHERE user_id = identity` filter (§5),
  which requires `AUTH_TYPE=custom`.** Under `noop` (current posture) every request is `anonymous`, so
  that filter is a no-op and all threads are mutually visible.
- **Google OAuth (Plane 2):** access token stored in an encrypted httpOnly `gw_tokens` cookie
  (`apps/web/lib/google.ts:24, 48-53, 141-147`), injected per-run via
  `configurable.google_access_token` (`apps/web/lib/run-config.ts:21-29`) on every submit. Refresh
  token never leaves the server. Clean two-plane separation — but the access token lands in
  checkpoints (§4).
- **No tenant/org in the frontend** — grep clean; only single-identity UI copy
  (`sign-in-gate.tsx:19` "private to your Google account").

---

## Tenancy verdict (one paragraph)

**Nora is single-user-per-account within a single shared org — and that isolation is real only when an
operator explicitly sets `AUTH_TYPE=custom`, which is neither the default nor the current
configuration.** There is no organization/tenant abstraction anywhere: no `tenant_id`/`org_id` column,
no RLS, no schema-/db-per-tenant, and no org claim in the token — the only isolation key is a flat
`user_id` (`sub`/`email`). Under `AUTH_TYPE=custom`, Aegra's hard-coded per-identity filters
(`WHERE user_id = identity` for threads/runs; `apply_user_namespace_scoping` for the REST store) *do*
give genuine per-operator isolation of threads and the REST store, which backstops the frontend's
user-unscoped thread search. But the app's own "agentic memory" is a **global, read-only, shared
knowledge base** (two hardcoded `("curry_nomad", …)` namespaces with no user in the root), not
per-user memory; `langmem` is absent; and `Context.user_id` — the one hook that would namespace memory
by user — is dead code. **As deployed today (`AUTH_TYPE=noop`, workspace enabled), every request is the
same `anonymous` identity, so there is effectively no tenancy isolation at all.** Not ready for
multi-tenant use; capable of single-org per-user isolation after the fixes below.

## Prioritized gaps (what would let one tenant's data reach another)

1. **`AUTH_TYPE=noop` in effect → single shared `anonymous` identity.** All threads and the entire
   REST store collapse into `["users","anonymous"]` / `user_id="anonymous"`; every operator sees every
   other operator's threads and memory. (`docker-compose.yml:62`, live `.env:70`, `auth.py:71-72`,
   `aegra_api/core/auth_middleware.py:238`.) *Fix:* set `AUTH_TYPE=custom` + `NEXTAUTH_SECRET` before
   any multi-user exposure.
2. **No `@auth.on` handlers + no tenant tier.** Isolation is per-*user* only, entirely dependent on
   Aegra's built-in `user_id` filtering. There is no `tenant_id`/`org_id` column and no RLS, so a
   single application bug (or any code path that reaches the raw store/checkpoint by `prefix`/`thread_id`)
   has no database-level backstop. *Fix:* add a tenant claim + `@auth.on`/`@auth.on.store` handlers,
   and/or RLS keyed on a verified `SET`-injected identity, for defense-in-depth.
3. **Memory namespace root is a global literal, not the user.** `("curry_nomad", …)` is shared by all
   operators (`memory.py:34-35`, `analytics/graph.py:173`, `marketing/nodes.py:104`). Harmless while
   memory is read-only seed data, but the moment any per-user write is added it will land in a global
   namespace unless the root is changed to the user id. `Context.user_id` (`schemas.py:233`) is unused.
   *Fix:* namespace in-graph memory as `(user_id, …)` using `configurable.user_id` /
   `langgraph_auth_user`, which Aegra already injects.
4. **In-graph store writes are not platform-scoped.** Aegra scopes only the REST `/store` surface;
   the graph gets the raw `AsyncPostgresStore` (`aegra_api/services/langgraph_service.py:354`). Any
   future agentic-memory write inside the graph bypasses `apply_user_namespace_scoping`. (Also produces
   the seed-vs-read namespace mismatch flagged in §3.) *Fix:* have graph code build the namespace from
   the injected identity; do not rely on the REST-layer rewrite.
5. **Client-chosen `thread_id` + user-unscoped thread listing.** `?threadId=` is client-controlled and
   the sidebar lists by `graph_id` only (`Stream.tsx:30`, `Thread.tsx:40-41`). Safe **only** because
   Aegra re-checks `thread.user_id` — and only under custom auth. Under `noop` this is a direct
   cross-user read. *Fix:* covered by #1; optionally scope the client search by user too.
6. **Checkpoint carries the Google access token; worker/cron trust stored identity.** OAuth token at
   rest in checkpoints (`orchestrator.py:556-559`); worker replays `execution_params.user` without
   re-verification and cron liveness is a no-op stub by default
   (`aegra_api/services/cron_scheduler.py:71-80`). Lower priority for this app (no crons used), but
   relevant if crons/background memory jobs are added.

## Could not determine (explicit)

> **Update (resolved during implementation on branch `feat/per-user-memory-tenancy`):** the first two
> items below were subsequently investigated in the Aegra source and are no longer open — see
> **Resolution & correction** at the end of this file. The seed mismatch is now fixed in code (still
> wants one live end-to-end check), and the "foreign prefix" concern turned out to have a concrete,
> confirmed vector (client-spoofable `configurable.user_id`) that the implementation closes.

- **Whether the seeded brand/definitions memory is actually readable on the Aegra platform path.** The
  REST-scoped write vs raw in-graph read (§3) strongly suggests a namespace mismatch, but confirming it
  requires running a live Aegra instance and inspecting the `store` table — not doable read-only.
  *(Addressed: the seed now writes straight to the raw store at `global.*` — the same prefixes the graph
  reads. Live verify still recommended.)*
- **Aegra's exact behavior for a `search` across namespaces on the raw in-graph store** (whether it
  could ever return another user's `["users",…]` items) — the REST path is scoped, but I did not trace
  every code path of the raw `AsyncPostgresStore.search` under a graph-supplied prefix. The store DDL
  (`prefix`-only key) means cross-namespace reads are possible *if* a caller supplies a foreign prefix;
  no app code does, but this is a property of the raw store, not a guarantee against it.
  *(Confirmed + mitigated: the concrete foreign-prefix vector is a client-spoofable
  `configurable.user_id`; the implementation's `resolve_user_id` reads the authoritative
  `langgraph_auth_user.identity` instead — see below.)*
- **No `apps/web/middleware.ts`** exists (confirmed absent) — so there is no edge-level per-user gate;
  isolation depends wholly on the Aegra backend as described.

---

## Resolution & correction (post-audit implementation)

Investigated in the Aegra 0.9.22 source while implementing per-user memory. One correction to a prior
assumption, material enough to record:

### `configurable.user_id` is NOT server-authoritative — it is client-spoofable

The natural resolver (`resolve_user_id` reading `configurable.user_id`) is **insecure**. On the run
path a client-supplied `configurable.user_id` survives to the graph:

- `aegra_api/utils/run_utils.py:11` — `SERVER_PINNED_CONFIG_KEYS = frozenset({"thread_id", "run_id"})`
  — `user_id` is **not** pinned/stripped.
- `aegra_api/services/langgraph_service.py:717,721-722` — `create_run_config` deep-copies the client
  body and hard-overwrites only `thread_id`/`run_id`.
- `aegra_api/services/langgraph_service.py:751` → `inject_user_context`, whose
  `:681` `configurable.setdefault("user_id", user.identity)` is a **no-op if the client already set
  it**, while `:684` `configurable["langgraph_auth_user"] = user` is a **hard assignment**.

**Exploit:** an authenticated operator A submits `config.configurable.user_id = "B"`; the graph then
sees `user_id = "B"`, and a resolver trusting it would read/write **B's** private memory. It passes in
honest testing (when nobody forges the field) and only leaks adversarially.

**Fix (implemented):** `nora/memory.py:resolve_user_id` reads `configurable.langgraph_auth_user.identity`
— the only hard-set, server-authoritative value — and never `configurable.user_id`. This is the
concrete resolution of the second "could not determine" item (the raw-store foreign-prefix concern):
the only per-user prefix the graph ever builds comes from the verified identity. Guarded by
`apps/nora/tests/test_memory_tenancy.py::test_resolve_user_id_ignores_client_supplied_user_id` and
`::test_remember_user_ignores_spoofed_user_id`.

### What shipped on `feat/per-user-memory-tenancy`

Two-tier memory (`global.*` shared + `users.<id>.*` private), the corrected resolver as the single
isolation choke point, per-user `save_memory`/`search_memory` agent tools (global writes gated,
`propose_global` dormant), the read sites repointed to `global.*`, the seed rewritten to write the raw
store (fixing the mismatch), and `Context.user_id` deleted. Full detail in
`docs/tenancy/per-user-memory-implementation.md`.

**Still owner-action / not code:** flip `AUTH_TYPE=custom` + match `NEXTAUTH_SECRET`/`AUTH_SECRET`
(gap #1 above). Until then every request is the shared `anonymous` identity and per-user memory
correctly no-ops.
