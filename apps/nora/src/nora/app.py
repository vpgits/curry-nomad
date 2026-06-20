"""Demo CLI — one entrypoint to run a turn end-to-end.

    python -m nora.app "What was our best-selling product in Colombo last quarter?"

M1 wires the analytics agent directly. M4 swaps `build_analytics_graph()` for the
orchestrator and adds the human-review interrupt prompt — the streaming/HITL plumbing in
`run_turn` is already written generically so that swap is a one-liner.

Streaming uses the stable `graph.stream(stream_mode=...)` API so the live demo runs
predictably. (The experimental v3 typed stream — `graph.stream_events(..., version="v3")`
with `.messages` / `.interrupts` / `.output` — is the alternative noted in the specs.)
"""

from __future__ import annotations

import sys

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command

from nora.config import get_settings
from nora.memory import build_checkpointer, build_store, seed_brand_knowledge
from nora.observability import bind_context, get_logger, setup_logging
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


def run_turn(graph, text: str, thread_id: str = THREAD_ID) -> dict:
    """Stream one turn through the graph, printing progress. Resumes from any HITL interrupt
    by prompting the operator. Returns the final state."""
    config = {"configurable": {"thread_id": thread_id}}
    inputs: dict | Command = {"messages": [HumanMessage(content=text)]}

    while True:
        for _node, update in graph.stream(inputs, config, stream_mode="updates"):
            if not isinstance(update, dict):
                continue
            for msg in update.get("messages", []):
                _print_message(msg)

        state = graph.get_state(config)
        if not state.interrupts:
            return state.values

        # A node raised interrupt() — surface it to the operator and resume (M3/M4 path).
        payload = state.interrupts[0].value
        inputs = _handle_interrupt(payload)


def _handle_interrupt(payload) -> Command:
    """Prompt the operator for an approve/edit/reject decision and build the resume Command."""
    question = payload.get("question", "Approve?") if isinstance(payload, dict) else str(payload)
    print(f"\n⏸  {question}")
    if isinstance(payload, dict) and payload.get("script_beats"):
        for beat in payload["script_beats"]:
            print(f"    [{beat['t_start_s']}-{beat['t_end_s']}s] {beat['voiceover']}")
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
    run_turn(graph, user_input)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
