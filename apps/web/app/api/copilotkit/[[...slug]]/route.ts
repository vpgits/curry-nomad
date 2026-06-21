import {
  CopilotRuntime,
  createCopilotHonoHandler,
  InMemoryAgentRunner,
} from "@copilotkit/runtime/v2";
import { LangGraphAgent } from "@copilotkit/runtime/langgraph";
import { handle } from "hono/vercel";

// CopilotKit runtime → AG-UI → the existing Nora LangGraph graph on Aegra (Agent Protocol).
// LangGraphAgent targets the LangGraph "deployment" surface (threads/runs/stream), which Aegra
// implements drop-in — so this reuses the whole orchestrator (analytics agent, marketing
// workflow, HITL, memory) rather than a standalone BuiltInAgent. This route runs server-side, so
// it uses the server-reachable Aegra URL (AEGRA_URL), not the browser-facing NEXT_PUBLIC one.
const AEGRA_URL = process.env.AEGRA_URL ?? "http://localhost:2026";
const GRAPH_ID = process.env.NEXT_PUBLIC_ASSISTANT_ID ?? "nora";

const runtime = new CopilotRuntime({
  agents: {
    default: new LangGraphAgent({
      deploymentUrl: AEGRA_URL,
      graphId: GRAPH_ID,
      // Optional — Aegra is keyless locally. Pass through if auth is enabled.
      langsmithApiKey: process.env.LANGSMITH_API_KEY ?? "",
    }),
  },
  runner: new InMemoryAgentRunner(),
});

const app = createCopilotHonoHandler({
  runtime,
  basePath: "/api/copilotkit",
});

// Multi-route handler: GET/POST drive run/connect/info; PATCH/DELETE serve thread operations.
export const GET = handle(app);
export const POST = handle(app);
export const PATCH = handle(app);
export const DELETE = handle(app);
