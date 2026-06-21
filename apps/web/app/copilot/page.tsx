"use client";

import { useEffect, useRef, useState } from "react";
import {
  CopilotKit,
  CopilotChat,
  useAgent,
  useInterrupt,
  UseAgentUpdate,
} from "@copilotkit/react-core/v2";
import "@copilotkit/react-core/v2/styles.css";
import { useQueryState } from "nuqs";

import { AppShell } from "@/components/app-shell";
import { ApprovalCard } from "@/components/ApprovalCard";
import type { ReviewDecision, ReviewInterrupt } from "@/lib/types";
import { sleep, tagThread } from "@/lib/threads";
import { useThreads } from "@/providers/Thread";

// The CopilotKit variant of the Nora chat, for side-by-side comparison with the custom useStream
// UI at `/`. It talks to the SAME Nora graph on Aegra, via the CopilotKit runtime route
// (app/api/copilotkit) → AG-UI → LangGraphAgent → Aegra. useSingleEndpoint={false} matches the
// multi-route Hono handler in that route. The shared AppShell sidebar lists threads from both
// surfaces; clicking a CopilotKit thread routes here with ?threadId=… (see AppSidebar).
export default function CopilotPage() {
  // threadId in the URL: set → load that conversation; null → a fresh chat. The sidebar writes it.
  const [threadId] = useQueryState("threadId");
  return (
    <CopilotKit runtimeUrl="/api/copilotkit" useSingleEndpoint={false}>
      {/* Both hooks must live inside <CopilotKit> to observe the active agent run. */}
      <MarketingReviewInterrupt />
      <CopilotThreadTagger />
      <AppShell
        title={
          <>
            Nora · <span className="text-muted-foreground">CopilotKit</span>
          </>
        }
        subtitle="Same Nora backend (Aegra), rendered with CopilotKit over AG-UI."
      >
        <div className="min-h-0 flex-1">
          {/* key remounts the chat when switching threads so it reconnects cleanly. */}
          <CopilotChat
            key={threadId ?? "new"}
            threadId={threadId ?? undefined}
            hasExplicitThreadId={!!threadId}
            className="h-full"
          />
        </div>
      </AppShell>
    </CopilotKit>
  );
}

// Tags each CopilotKit-created thread with source "copilot" (+ a title) once its first run
// finishes, so the shared history sidebar can label it and route clicks back here — mirrors what
// StreamProvider does for the `/` surface. Then refetches the thread list so it appears labelled.
function CopilotThreadTagger() {
  const { agent } = useAgent({ updates: [UseAgentUpdate.OnRunStatusChanged] });
  const { getThreads, setThreads } = useThreads();
  const tagged = useRef<Set<string>>(new Set());
  const wasRunning = useRef(false);

  const running = agent.isRunning;
  const threadId = agent.threadId;

  useEffect(() => {
    const justFinished = wasRunning.current && !running;
    wasRunning.current = running;
    if (!justFinished || !threadId || tagged.current.has(threadId)) return;
    tagged.current.add(threadId);
    // A just-created thread isn't immediately searchable; tag after a beat, then refresh the list.
    sleep()
      .then(() => tagThread(threadId, "copilot"))
      .then(() => getThreads())
      .then(setThreads)
      .catch((err) => {
        tagged.current.delete(threadId); // let a later run retry
        console.error(err);
      });
  }, [running, threadId, getThreads, setThreads]);

  return null;
}

// The marketing workflow pauses at a human-review interrupt() before the expensive creative steps.
// useInterrupt surfaces that backend interrupt to the client; `event.value` is the same
// ReviewInterrupt payload the `/` UI reads, and `resolve(decision)` resumes the run with a
// Command(resume=decision) — i.e. the ReviewDecision read by the marketing human_review node. We
// render the SAME ApprovalCard the canonical `/` UI uses; renderInChat (the default) draws it
// inline in the chat thread. Without this, an ad request on `/copilot` would stall at the gate.
function MarketingReviewInterrupt() {
  useInterrupt({
    render: ({ event, resolve }) => (
      <ReviewInterruptCard
        payload={event.value as ReviewInterrupt}
        onDecide={(decision) => resolve(decision)}
      />
    ),
  });
  return null;
}

// Owns the post-click "submitting" state so the approve/edit/reject buttons disable after the
// first decision — resolve() resumes the run exactly once, then the interrupt clears and this
// unmounts. (useInterrupt re-invokes render on each parent render; a real component keeps state.)
function ReviewInterruptCard({
  payload,
  onDecide,
}: {
  payload: ReviewInterrupt;
  onDecide: (decision: ReviewDecision) => void;
}) {
  const [submitting, setSubmitting] = useState(false);
  return (
    <ApprovalCard
      payload={payload}
      disabled={submitting}
      onDecision={(decision) => {
        setSubmitting(true);
        onDecide(decision);
      }}
    />
  );
}
