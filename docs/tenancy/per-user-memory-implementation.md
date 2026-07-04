# Per-user memory — implementation (as built)

Branch `feat/per-user-memory-tenancy`. This is the implementation plan **with the security
correction folded in** — the original plan's `resolve_user_id` read `configurable.user_id`, which is
client-spoofable; see `NORA_TENANCY_AUDIT.md` §"Resolution & correction" for the evidence chain. Every
per-user namespace is built only from the server-injected identity — that discipline is the isolation
control (there is no RLS).

## Guardrails (unchanged from plan; all satisfied)

- Per-user namespaces are built ONLY from `resolve_user_id(config)` — never a client value.
- `resolve_user_id` → `None` is a hard no-op, never a shared-namespace fallback.
- `write_global` / `propose_global` are **not** agent tools. Agent gets `save_memory` + `search_memory`.
- Global memory is seeded via the **raw** store, never the REST API.
- No `tenant_id`/`org_id`, no org claim, no RLS-as-primary, no review UI (all deferred).
- `Context.user_id` deleted, not wired.

## Changes

### `apps/nora/src/nora/memory.py` (rewritten)
- **Namespace scheme:** `global_ns(*parts)` → `("global", …)`; `user_ns(user_id, *parts)` →
  `("users", user_id, …)` with an empty-id guard. Per-user root aligns with Aegra's REST store
  scoping (`["users", <id>, …]`). `GLOBAL_BRAND` / `GLOBAL_DEFINITIONS` / `GLOBAL_OPERATIONS`.
- **`resolve_user_id(config)` — the choke point (CORRECTED):** reads
  `configurable.langgraph_auth_user.identity` (server-hard-set at `langgraph_service.py:684`), NOT
  `configurable.user_id` (client-spoofable — `setdefault` + not pinned). Returns `None` for
  no-auth / `anonymous`.
- **`recall` / `remember_user` / `write_global` (gated `authorized=`) / `propose_global` (dormant).**
- **Agent tools `save_memory` / `search_memory`** (`MEMORY_TOOLS`) — reach the runtime store/config via
  `langgraph.config.get_store()` / `get_config()`; degrade to a message (never raise) so ToolNode's
  narrow `SqlError` handler stays narrow.
- Seed knowledge repointed to the `GLOBAL_*` namespaces.

### `apps/nora/src/nora/analytics/graph.py`
- Reads `GLOBAL_DEFINITIONS` (was `DEFINITIONS`).
- Binds `[*ANALYTICS_TOOLS, *MEMORY_TOOLS]` to the model and ToolNode. `ANALYTICS_TOOL_NAMES` stays
  DB-tools-only, so the "did it engage the DB?" query guard does not count a memory-tool call.

### `apps/nora/src/nora/marketing/nodes.py`
- `load_brand` reads `GLOBAL_BRAND` (was `BRAND`).

### `apps/nora/src/nora/schemas.py`
- `Context.user_id` removed (identity comes from `resolve_user_id`).

### Seed (fixes the mismatch bug)
- `apps/nora/scripts/seed_store.py` deleted; `apps/nora/scripts/seed_global.py` added — writes the
  GLOBAL tier straight to Postgres via `AsyncPostgresStore` (raw store), so the seed lands at the
  `global.*` prefixes the graph reads. `docker-compose.yml` `seed` service repointed to it (direct
  `DATABASE_URL`, `.env` for the embedding key, still ordered after `aegra` healthy).

### Tests
- `apps/nora/tests/test_memory_tenancy.py` (new) — namespace builders, resolver, the **spoof guards**
  (`test_resolve_user_id_ignores_client_supplied_user_id`, `test_remember_user_ignores_spoofed_user_id`),
  cross-user isolation, gated global write, and the tool-surface guardrail.
- `apps/nora/tests/test_hitl_memory.py` — updated to the `GLOBAL_*` namespaces.
- **163 passed, 6 skipped** (offline suite); `ruff check .` clean.

## Not done here (owner action / deferred)

- **Step 0 — `AUTH_TYPE=custom` + `NEXTAUTH_SECRET`/`AUTH_SECRET` match.** Config + secrets, left to
  the operator. Until set, every request is `anonymous` and per-user memory correctly no-ops.
- **Live end-to-end check** on Aegra: seed, then confirm a signed-in operator's brand/definitions
  lookup returns the `global.*` items, a per-user `save_memory` persists cross-thread, and a second
  operator can't see it. Requires the running stack.
- **Verify `langgraph_auth_user` propagates into the analytics *subgraph* tool config.** Analytics
  runs as a subgraph node; if the key were stripped at the boundary the resolver would see `None` and
  per-user memory would silently no-op (fail-safe, not fail-open). Confirm on the live stack.
- **Deferred forks (untouched):** org/tenant tier + RLS, accumulation (`propose_global` is the dormant
  seam) + review UI/reviewer identity, and the orthogonal "Google token in checkpoints" secrets-at-rest
  ticket.
