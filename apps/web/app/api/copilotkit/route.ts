// CopilotKit self-hosted runtime — the ONLY backend layer reintroduced for the /copilot
// experiment. It is a thin proxy: every request is forwarded to the `nora` graph already served
// by `langgraph dev` over the Agent Protocol on :2024. Crucially this is the *durable* path —
// `LangGraphAgent` reads/writes threads through the Platform Threads API (the same store
// `useStream` uses on `/`), so there is NO in-process thread store like the old
// `InMemoryAgentRunner` that made thread reloads come back empty. See the experiment notes.
//
// `ExperimentalEmptyAdapter` = agent-lock mode: the LLM lives inside the graph, so the runtime
// needs no LLM service adapter of its own (suggestions/CopilotTextarea would, but we use neither).
import {
  CopilotRuntime,
  ExperimentalEmptyAdapter,
  copilotRuntimeNextJSAppRouterEndpoint,
} from "@copilotkit/runtime";
import { LangGraphAgent } from "@copilotkit/runtime/langgraph";
import { NextRequest } from "next/server";

const DEPLOYMENT_URL = process.env.LANGGRAPH_DEPLOYMENT_URL ?? "http://localhost:2024";

const runtime = new CopilotRuntime({
  agents: {
    // The key is the agent id the frontend locks onto (<CopilotKit agent="nora">); graphId is the
    // graph registered in langgraph.json. They match by convention here.
    nora: new LangGraphAgent({
      deploymentUrl: DEPLOYMENT_URL,
      graphId: "nora",
      // Optional; the local dev server is keyless. Forwarded to LangSmith when present.
      langsmithApiKey: process.env.LANGSMITH_API_KEY ?? "",
    }),
  },
});

const serviceAdapter = new ExperimentalEmptyAdapter();

export const POST = async (req: NextRequest) => {
  const { handleRequest } = copilotRuntimeNextJSAppRouterEndpoint({
    runtime,
    serviceAdapter,
    endpoint: "/api/copilotkit",
  });
  return handleRequest(req);
};
