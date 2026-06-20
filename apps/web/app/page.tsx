"use client";

import { useState } from "react";
import { useStream } from "@langchain/langgraph-sdk/react";
import { ApprovalCard } from "@/components/ApprovalCard";
import { VideoBriefCard } from "@/components/VideoBriefCard";
import type { NoraState, ReviewDecision, ReviewInterrupt, VideoBrief } from "@/lib/types";

const API_URL = process.env.NEXT_PUBLIC_AEGRA_URL ?? "http://localhost:2026";
const ASSISTANT_ID = process.env.NEXT_PUBLIC_ASSISTANT_ID ?? "nora";

const SUGGESTIONS = [
  "What was our best-selling product in Colombo last quarter?",
  "Make a 30s video ad for it",
  "What's the refund rate on blends?",
];

function textOf(content: unknown): string {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content.map((b: unknown) => (typeof b === "string" ? b : ((b as { text?: string })?.text ?? ""))).join("");
  }
  return "";
}

export default function Home() {
  const [input, setInput] = useState("");

  // useStream manages one thread for the session, so the canonical flow (ask → answer →
  // "make a video ad for it" → review → finish) runs on a single thread, and the HITL
  // interrupt is surfaced as `thread.interrupt`.
  const thread = useStream<NoraState>({
    apiUrl: API_URL,
    assistantId: ASSISTANT_ID,
    messagesKey: "messages",
  });

  const interrupt = thread.interrupt?.value as ReviewInterrupt | undefined;

  const send = (text: string) => {
    const content = text.trim();
    if (!content || thread.isLoading) return;
    setInput("");
    thread.submit({ messages: [{ type: "human", content }] });
  };

  // Resume the paused marketing workflow with the operator's decision (our custom payload,
  // read by human_review in nodes.py).
  const decide = (decision: ReviewDecision) => {
    thread.submit(undefined, { command: { resume: decision } });
  };

  return (
    <main className="app">
      <header className="header">
        <h1>
          Nora · <span className="spice">Curry Nomad</span>
        </h1>
        <p>
          One assistant, two paradigms — an analytics <b>agent</b> and a marketing <b>workflow</b>,
          served over Aegra.
        </p>
      </header>

      <div className="suggestions">
        {SUGGESTIONS.map((s) => (
          <button key={s} className="chip" onClick={() => send(s)} disabled={thread.isLoading}>
            {s}
          </button>
        ))}
      </div>

      <div className="messages">
        {thread.messages.map((message, idx) => (
          <MessageView key={(message as { id?: string }).id ?? idx} message={message} />
        ))}

        {interrupt && (
          <ApprovalCard payload={interrupt} disabled={thread.isLoading} onDecision={decide} />
        )}

        {thread.isLoading && <div className="dots">Nora is thinking…</div>}
        {thread.error ? (
          <div className="error">{String((thread.error as { message?: string })?.message ?? thread.error)}</div>
        ) : null}
      </div>

      <div className="composer">
        <form
          className="inner"
          onSubmit={(e) => {
            e.preventDefault();
            send(input);
          }}
        >
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about the business, or ask for a video ad…"
            disabled={thread.isLoading}
          />
          <button className="btn approve" type="submit" disabled={thread.isLoading || !input.trim()}>
            Send
          </button>
        </form>
      </div>
    </main>
  );
}

function MessageView({ message }: { message: unknown }) {
  const m = message as {
    type: string;
    content: unknown;
    tool_calls?: { name: string; args: Record<string, unknown> }[];
    additional_kwargs?: { video_brief?: VideoBrief };
  };

  if (m.type === "human") {
    return <div className="msg human">{textOf(m.content)}</div>;
  }

  if (m.type === "ai") {
    const text = textOf(m.content);
    const toolCalls = m.tool_calls ?? [];
    const brief = m.additional_kwargs?.video_brief;
    return (
      <div className="msg ai">
        <div className="role">Nora</div>
        {text && <div>{text}</div>}
        {toolCalls.map((tc, i) => (
          <div className="toolcall" key={i}>
            ⚙ {tc.name}({JSON.stringify(tc.args)})
          </div>
        ))}
        {brief && (
          <div style={{ marginTop: 12 }}>
            <VideoBriefCard brief={brief} />
          </div>
        )}
      </div>
    );
  }

  return null; // tool/system messages from the orchestrator level are hidden
}
