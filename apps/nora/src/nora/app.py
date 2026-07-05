"""Demo CLI — one entrypoint to run a turn end-to-end.

    python -m nora.app "What was our best-selling product in Colombo last quarter?"

M1 wires the analytics agent directly. M4 swaps `build_analytics_graph()` for the
orchestrator and adds the human-review interrupt prompt — the streaming/HITL plumbing in
`run_turn` is already written generically so that swap is a one-liner.

Streaming uses the async `graph.astream(stream_mode=...)` API: the orchestrator runs async so the
workspace agent's coroutine-only MCP tools work without an `asyncio.run` bridge (sync nodes still
run fine, in a worker thread). (The experimental v3 typed stream — `graph.astream_events(...,
version="v3")` — is the alternative noted in the specs.)
"""

from __future__ import annotations

import asyncio
import sys

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command

from nora.config import get_settings
from nora.memory import build_checkpointer, build_store, seed_brand_knowledge
from nora.observability import (
    bind_context,
    flush_langfuse,
    get_langfuse_handler,
    get_logger,
    setup_logging,
)
from nora.orchestrator import build_orchestrator

log = get_logger(__name__)

THREAD_ID = "demo-1"


def _print_message(msg) -> None:
    """Render one streamed message for the live demo."""
    if isinstance(msg, AIMessage):
        for call in msg.tool_calls or []:
            print(f"  ⚙️  tool call: {call['name']}({call['args']})")
        if msg.content:
            print(f"\nNora: {msg.content}")
    elif isinstance(msg, ToolMessage):
        preview = str(msg.content).replace("\n", " ")
        if len(preview) > 200:
            preview = preview[:200] + "…"
        print(f"  ↳ tool result: {preview}")


async def run_turn(graph, text: str, thread_id: str = THREAD_ID) -> dict:
    """Stream one turn through the graph, printing progress. Resumes from any HITL interrupt
    by prompting the operator. Returns the final state."""
    config = {"configurable": {"thread_id": thread_id}}

    # Optional Langfuse tracing: one attach point covers the whole turn. The orchestrator passes
    # this same `config` into the analytics agent and the marketing workflow, so the callback
    # propagates everywhere automatically. No-op when Langfuse isn't configured (handler is None).
    handler = get_langfuse_handler()
    if handler is not None:
        config["callbacks"] = [handler]
        # SDK v3 reads these off the run config's metadata (NOT constructor args). `session_id`
        # is warranted because this is a multi-turn chat thread — grouping the turns under the
        # thread_id lets the Langfuse Sessions view show the whole conversation together.
        config["metadata"] = {
            "langfuse_session_id": thread_id,
            "langfuse_tags": ["nora", "cli"],
            # Name each turn by its message (truncated) so the Sessions view reads like the
            # conversation — one named, ordered turn per trace — instead of N rows all named the same.
            "langfuse_trace_name": text[:80] if text else "nora-turn",
        }

    inputs: dict | Command = {"messages": [HumanMessage(content=text)]}

    while True:
        async for chunk in graph.astream(inputs, config, stream_mode="updates"):
            # stream_mode="updates" yields {node_name: node_update} per superstep — print the
            # messages from each node's update.
            for update in chunk.values():
                if isinstance(update, dict):
                    for msg in update.get("messages", []):
                        _print_message(msg)

        state = await graph.aget_state(config)
        if not state.interrupts:
            return state.values

        # A node raised interrupt() — surface it to the operator and resume (M3/M4 path).
        payload = state.interrupts[0].value
        inputs = _handle_interrupt(payload)


def _handle_interrupt(payload) -> Command:
    """Prompt the operator for an approve/edit/reject decision and build the resume Command."""
    question = payload.get("question", "Approve?") if isinstance(payload, dict) else str(payload)
    print(f"\n⏸  {question}")
    if isinstance(payload, dict) and payload.get("caption"):
        print(f"    caption: {payload['caption']}")
        for line in payload.get("on_screen_texts") or []:
            print(f"    · {line}")
    answer = input("    approve / reject ? [approve]: ").strip().lower() or "approve"
    approved = answer.startswith("a")
    log.info("hitl.resumed", decision="approve" if approved else "reject")
    return Command(resume={"approved": approved})


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print('usage: python -m nora.app "<your question or request>"')
        return 1

    setup_logging(json_logs=False)  # pretty console output for the live demo
    bind_context(thread_id=THREAD_ID)

    # Build the full orchestrator with memory wired in (short-term checkpointer + seeded
    # semantic Store). Both are shared into the analytics/marketing subgraphs.
    settings = get_settings()
    store = build_store(settings)
    seed_brand_knowledge(store)
    graph = build_orchestrator(
        settings=settings, checkpointer=build_checkpointer(), store=store
    )

    user_input = " ".join(argv)
    print(f"You: {user_input}")
    try:
        asyncio.run(run_turn(graph, user_input))
    finally:
        # The Langfuse SDK batches events in the background; flush before this short-lived
        # process exits or the trace may never be sent. No-op when Langfuse isn't configured.
        flush_langfuse()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
