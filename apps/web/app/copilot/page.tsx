"use client";

// EXPERIMENT (parallel surface): can CopilotKit be reintroduced cleanly against the Aegra backend?
// `/` (useStream) is the untouched control; this route is the A/B. The whole CopilotKit ↔ Nora link
// is: <CopilotKit> → /api/copilotkit (CopilotRuntime + LangGraphAgent) → Aegra. Threads are durable
// on Aegra (Postgres-backed) — no InMemoryAgentRunner.
import "@copilotkit/react-ui/styles.css";

import { CopilotKit, useLangGraphInterrupt } from "@copilotkit/react-core";
import { CopilotChat } from "@copilotkit/react-ui";
import Link from "next/link";

import { ApprovalCard } from "@/components/ApprovalCard";
import type { ReviewDecision, ReviewInterrupt } from "@/lib/types";

// Registers the marketing HITL gate with CopilotKit. The render is injected into the chat
// transcript when the `nora` graph hits `interrupt()`. Inbound: CopilotKit JSON-parses the
// interrupt payload, so `event.value` is already a `ReviewInterrupt`. Outbound: `resolve` is
// string-typed, so we JSON.stringify the decision — the backend `human_review` json.loads it back
// into the same dict useStream would have sent via Command(resume=...).
function MarketingApprovalGate() {
  useLangGraphInterrupt<ReviewInterrupt>({
    agentId: "nora",
    render: ({ event, resolve }) => (
      <ApprovalCard
        payload={event.value}
        disabled={false}
        onDecision={(decision: ReviewDecision) => resolve(JSON.stringify(decision))}
      />
    ),
  });
  return null;
}

export default function CopilotPage() {
  return (
    // agent="nora" → agent-lock mode: the graph drives the whole chat, the runtime needs no LLM
    // adapter of its own (ExperimentalEmptyAdapter in the route).
    <CopilotKit runtimeUrl="/api/copilotkit" agent="nora">
      <MarketingApprovalGate />
      <div className="flex h-svh flex-col">
        <header className="flex items-center justify-between border-b px-4 py-2 text-sm">
          <span className="font-medium">Nora — CopilotKit surface (experiment)</span>
          <Link href="/" className="text-muted-foreground underline-offset-2 hover:underline">
            ← back to / (useStream)
          </Link>
        </header>
        <div className="min-h-0 flex-1">
          <CopilotChat
            className="h-full"
            labels={{
              title: "Nora (CopilotKit)",
              initial:
                "Hi, I'm Nora on the CopilotKit surface. Ask me for analytics, or to draft a video ad.",
            }}
          />
        </div>
      </div>
    </CopilotKit>
  );
}
