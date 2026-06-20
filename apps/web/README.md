# Curry Nomad — web UI

A small **Next.js (App Router + TypeScript)** chat frontend for Nora. It talks to the `nora`
graph through **Aegra** (the self-hosted Agent Protocol backend) using the official
[`@langchain/langgraph-sdk`](https://www.npmjs.com/package/@langchain/langgraph-sdk) `useStream`
hook — so streaming, threads, and human-in-the-loop interrupts are handled by the SDK, not a
hand-rolled API client.

```
Next.js (useStream) ──Agent Protocol──▶ Aegra ──▶ nora orchestrator graph
```

## What it shows

- A chat box that streams Nora's answers.
- The analytics **agent**'s replies (and any tool calls it surfaces).
- The marketing **workflow**'s human-review gate as an **approval card** — approve, edit the
  script in place, or reject — which resumes the paused run.
- The final **VideoBrief** rendered as a card (concept, hook, script, shots, CTA, hashtags,
  and the real product facts it was grounded in).

The canonical demo runs on one thread: *"best-selling product in Colombo?"* → answer →
*"make a video ad for it"* → approval card → brief.

## Run

First start the backend (from the repo root) and seed memory:

```bash
uv sync --extra aegra
cp .env.example .env          # add OPENAI_API_KEY
uv run aegra dev              # serves the nora graph on http://localhost:2026 (+ Postgres via Docker)
uv run python apps/nora/scripts/seed_store.py   # seed brand voice + metric definitions into the store
```

Then the frontend:

```bash
cd apps/web
cp .env.local.example .env.local   # NEXT_PUBLIC_AEGRA_URL=http://localhost:2026
npm install
npm run dev                        # http://localhost:3000
```

`aegra.json` allows CORS from `http://localhost:3000`. Requires Docker (for Postgres) and an
OpenAI key (chat models + the semantic store embeddings).
