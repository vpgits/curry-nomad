# Data & Evaluation Spec

> The bundled dataset and the dual-eval harness. The dataset being self-owned is what makes deterministic evals possible — that's the whole reason analytics can be graded automatically.

## 1. The dataset — synthetic Curry Nomad (Sri Lankan spice business)

Built by `src/nora/data/seed.py` into a committed `curry_nomad.db` (SQLite). Generation is **deterministic**: `rng = random.Random(42)`, fixed date window, no wall-clock calls — re-running the seed reproduces the same DB byte-for-byte (so evals are stable). All money in **LKR (integers, cents avoided)**.

**Date window:** orders span `2025-07-01 … 2026-06-30`, ending exactly on `config.data_as_of`. This makes "last quarter", "last month", "this year" deterministically answerable.

**Approximate volumes:** ~18 products, ~120 customers, ~1,500 orders, ~3,500 order_items, ~90 refunds.

### Schema

```sql
products(
  product_id    INTEGER PRIMARY KEY,
  name          TEXT,        -- "Ceylon Cinnamon (Alba)", "Black Pepper", "Roasted Curry Powder", ...
  category      TEXT,        -- 'whole_spice' | 'ground_spice' | 'blend' | 'specialty'
  origin        TEXT,        -- 'Matale','Kandy','Galle','Jaffna','Mirissa', ...
  grams         INTEGER,     -- pack size
  unit_price_lkr INTEGER,
  sku           TEXT UNIQUE,
  active        INTEGER      -- 0/1
)

customers(
  customer_id   INTEGER PRIMARY KEY,
  name          TEXT,        -- Sri Lankan names
  city          TEXT,        -- 'Colombo','Kandy','Galle','Jaffna','Negombo','Matara', + a few export cities
  segment       TEXT,        -- 'local' | 'export'
  created_at    TEXT         -- ISO date
)

orders(
  order_id      INTEGER PRIMARY KEY,
  customer_id   INTEGER REFERENCES customers,
  order_date    TEXT,        -- ISO date within the window
  status        TEXT,        -- 'completed' | 'cancelled' | 'refunded'
  channel       TEXT         -- 'web' | 'whatsapp' | 'market_stall' | 'wholesale'
)

order_items(
  order_item_id  INTEGER PRIMARY KEY,
  order_id       INTEGER REFERENCES orders,
  product_id     INTEGER REFERENCES products,
  quantity       INTEGER,
  unit_price_lkr INTEGER     -- price at time of sale (denormalized)
)

refunds(
  refund_id     INTEGER PRIMARY KEY,
  order_id      INTEGER REFERENCES orders,
  amount_lkr    INTEGER,
  reason        TEXT,        -- 'damaged','late','wrong_item','quality'
  refund_date   TEXT
)
```

**Seeding realism (so questions have signal):** make a few products clearly top-sellers (Ceylon Cinnamon, Roasted Curry Powder); skew some cities heavier (Colombo > others); give curry kits / blends a slightly higher refund rate; make `export` orders larger but rarer. Document these "planted truths" in a comment so demo questions land.

**Grounding the marketing side:** the marketing workflow looks up the chosen product's real row (name, origin, grams, price, category) and the eval checks those facts appear in the brief.

## 2. Evaluation — two styles, taught in contrast

Runner: `evals/run_evals.py --suite {analytics|marketing|all} [--langsmith]`. Offline by default (runs the graphs against the bundled DB + configured model). `--langsmith` pushes to LangSmith `evaluate` for the dashboard view. Evaluators live in `evals/evaluators.py`.

### 2a. Analytics — deterministic / ground truth

`evals/analytics_dataset.jsonl`, one object per line:
```json
{"id":"a01","question":"What was our highest-revenue product last quarter?","reference_sql":"SELECT p.name, SUM(oi.quantity*oi.unit_price_lkr) rev FROM order_items oi JOIN orders o ON o.order_id=oi.order_id JOIN products p ON p.product_id=oi.product_id WHERE o.order_date>='2026-04-01' AND o.order_date<='2026-06-30' AND o.status!='cancelled' GROUP BY p.product_id ORDER BY rev DESC LIMIT 1","answer_type":"text","expects_recovery":false}
{"id":"a07","question":"What's the refund rate on blends?","reference_sql":"...","answer_type":"number","expects_recovery":false}
{"id":"a12","question":"Total revenue from Kandy customers this year, net of refunds.","reference_sql":"...","answer_type":"number","expects_recovery":false}
{"id":"a15","question":"Which channel has the highest average order value?","reference_sql":"...","answer_type":"text","expects_recovery":false}
{"id":"a20","question":"How many distinct export customers ordered Ceylon Cinnamon?","reference_sql":"...","answer_type":"number","expects_recovery":true}
```
- ~15–20 questions covering: aggregation, joins, time windows, group-by/top-N, refund math, segment/channel splits.
- At least 2 flagged `expects_recovery:true` — phrased to tempt a wrong column/table so the agent must read the SQL error and repair.

**Evaluators (per item):**
1. **`answer_correct`** — compute ground truth by running `reference_sql` against the DB; extract the agent's final answer (number/text/list); compare (numeric within tolerance; text normalized/contains; list set-equality). The truth is *derived*, never hand-typed.
2. **`valid_sql`** — every `run_sql` the agent executed parsed & returned without error on its final successful attempt.
3. **`recovered`** (only for `expects_recovery` items) — the run contains a `sql.error` event followed by a later successful `run_sql` and a correct answer.

**Metrics reported:** answer accuracy (%), SQL validity (%), recovery rate (% of recovery items), avg tool calls per question.

### 2b. Marketing — LLM-as-judge + deterministic guardrails

`evals/marketing_dataset.jsonl`:
```json
{"id":"m01","product_name":"Ceylon Cinnamon (Alba)","request":"30s reel highlighting authentic Matale origin"}
{"id":"m02","product_name":"Roasted Curry Powder","request":"punchy reel for a weekend promo"}
```
- ~6–8 items. For each, run the marketing workflow (auto-approve the HITL gate in eval mode — see note) and grade the resulting `VideoBrief`.

**Deterministic guardrails (hard checks on `VideoBrief`):**
- `target_duration_s` within `[25, 35]`.
- `2 ≤ len(shots) ≤ 8` and `len(shot_prompts) == len(shots)`.
- hook present: `script_beats[0].t_start_s == 0` and non-empty voiceover, first beat ends `≤ 3s`.
- `cta` non-empty.
- **product grounding:** the product's real name/origin appears in `product_facts_used` (and origin matches the DB row).
- **no banned claims:** none of a banned list (`"cure"`, `"guaranteed"`, `"#1 in the world"`, medical claims) appears in any voiceover/on-screen text.

**LLM-judge (rubric, 1–5):** a judge model (`init_chat_model(settings.model)` with `with_structured_output(JudgeScore)`) scores **brand-voice adherence** (warm, a little cheeky, proudly Sri Lankan; not generic AI ad copy) and **coherence/hook quality**, with a one-line justification. Rubric is a constant in `evaluators.py`.

**Metrics reported:** guardrail pass-rate (%), mean judge score, per-item breakdown.

> **HITL in eval mode:** the workflow exposes an `auto_approve` flag (or eval passes `Command(resume={"approved":True})` after the first interrupt) so evals run unattended. The interactive approve/edit/reject path is exercised in the demo and in `test_marketing_graph.py`, not in the batch eval.

## 3. Target thresholds (teaching targets, not SLAs)

| Metric | Target |
|---|---|
| Analytics answer accuracy | ≥ 0.80 |
| Analytics recovery rate | recovery items recover & answer correctly |
| Marketing guardrail pass-rate | ≥ 0.90 |
| Marketing judge mean | ≥ 4.0 / 5 |

These are printed by the runner and are the live "did our agent actually work?" moment in the session. Document that thresholds are illustrative and model-dependent.

## 4. What the eval section teaches (call out live)
- You **can** evaluate agents — but *how* depends on the task.
- Factual/tool agents → derive ground truth and check automatically (cheap, deterministic, CI-able).
- Creative/generative workflows → judge against a rubric + hard guardrails; never a single "right" answer.
- Trajectory matters, not just the final answer (the recovery metric).

---

## 5. Operations data — the writable DB (post-M8)

The operations subsystem (M8) owns a **second, writable** SQLite DB, deliberately separate from the read-only `curry_nomad.db` so the committed analytics dataset stays pristine. Built by `python -m nora.operations.seed` into `settings.ops_db_path` (gitignored `data/runtime/operations.db`), with the same discipline as the analytics seed — `random.Random(42)`, **no wall-clock** → byte-identical on re-run.

**Derived from the business DB:** it snapshots a subset of products/customers (so it's self-contained, no cross-DB ATTACH) and derives initial `on_hand` from each product's real historical sales volume, so stock numbers are plausible.

**Planted truths (so the demos have signal):**
- Initial `on_hand` ≈ 1.5 months of historical demand; reorder points ≈ half a month.
- A few SKUs (White Pepper, Green Cardamom, Cloves gift tin, Goraka) are seeded **below** reorder point, so `/stock/low` is non-empty out of the box.
- Eight pending deliveries are seeded across local cities in a deliberately **zig-zag** order, so a naive "visit-as-listed" route is clearly longer than the optimized one — the routing win is visible immediately (`naive_km` vs the 2-opt tour).

**Testing, not evals.** Operations is deterministic, so it isn't graded by the LLM eval harness — it's covered by direct unit tests (`test_operations_{services,routing,seed,api}.py`): the services' invariants (oversell rejection, atomic tx + ledger), the optimizer (optimized ≤ naive, deterministic), and the REST API. The generative-UI push is likewise asserted by `test_generative_ui.py`, not the eval suites (cards are best-effort, never load-bearing).
