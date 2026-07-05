"""`present_ui` — a generative-UI authoring TOOL that ANY agent can call mid-answer.

The contrast with the three post-hoc card pushers (`analytics_dashboard`, `marketing`, `workspace`
nodes attach a FIXED card after a capability finishes): here a *model* decides, while it is still
answering, that its data reads better as metrics/chart/table and renders an `A2uiSurface` inline. It's
the "any agent authors UI, on demand" generalization of the former /studio A2UI showcase — bound to
the supervisor AND the capability agents (analytics, workspace).

It's a plain LangChain `@tool` in the mould of the memory tools (`memory.py`): it reaches the running
graph through LangGraph's ambient context — `push_ui_message` internally calls `get_config()` /
`get_stream_writer()` — so it works from inside a tool during a live run.

Two hard problems this file solves, both verified against the installed langgraph:

1. **Association.** The web client renders a card only where `ui.metadata.message_id === message.id`
   (`apps/web/.../messages/ai.tsx`). A tool runs mid-loop, *before* the final answer message exists,
   so it associates the card with the CURRENT last AI message (the one that just called `present_ui`)
   read via LangGraph's `InjectedState`. The card then renders inline right after that message.

2. **Propagation.** `push_ui_message` writes the card into the `ui` state channel of the *currently
   executing* graph. For a push from inside the analytics **subgraph** to reach the top-level thread,
   `AnalyticsState` must declare a shared `ui` channel (see `state.py`) — LangGraph then propagates it
   up exactly like `messages`. The **imperative** workspace node can't rely on that (its inner loop's
   state is discarded), so the orchestrator re-emits any authored surfaces at the top level via
   `emit_present_ui_from_messages` — mirroring how the other imperative cards are pushed.

`InjectedState` is **optional (default `None`)** on purpose: the analytics/workspace-off/middleware
paths run the tool through a `ToolNode` (which injects real state), but the workspace *primitive* gate
executes it with a bare `tool.ainvoke(tool_call)` (no injection) — a required injected arg would crash
there. With the default, that path degrades to "no association" instead of raising (and the workspace
re-emit re-associates it anyway).

Everything here is **best-effort**: a bad surface or a missing stream never raises — generative UI is
a nicety layered on top of the text answer, never load-bearing for it.
"""

from __future__ import annotations

from typing import Annotated, Any

from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from langgraph.graph.ui import push_ui_message
from langgraph.prebuilt import InjectedState

from nora.observability import get_logger
from nora.schemas import A2uiBlock, A2uiSurface

log = get_logger(__name__)

# The card name the web client maps to `A2uiSurfaceView` (ai.tsx UI_COMPONENTS) — the same channel the
# analytics "Author UI" output mode already pushes, so no frontend change is needed to render it.
A2UI_SURFACE_CARD = "a2ui_surface"


def _last_ai_message(messages: list) -> AIMessage | None:
    """The most recent AIMessage in `messages` — at tool-execution time that's the very message that
    called `present_ui`, so the card binds to it and renders inline right after it."""
    for message in reversed(messages or []):
        if isinstance(message, AIMessage):
            return message
    return None


def push_surface(blocks: Any, message: AIMessage | None) -> bool:
    """Validate `blocks` into an `A2uiSurface` and push it as the `a2ui_surface` card, associated with
    `message` (→ `metadata.message_id`, which is how the web client binds a card to a message).

    Returns True iff a non-empty surface was pushed. Never raises: an invalid surface, or no stream / no
    `ui` channel in the current graph, both collapse to a skipped card — the text answer is untouched.
    Shared by the tool itself, the supervisor's direct-reply path, and the workspace re-emit."""
    try:
        surface = A2uiSurface(blocks=list(blocks or []))
    except Exception as exc:  # noqa: BLE001 — a malformed surface must never break the turn
        log.info("present_ui.invalid", error=str(exc))
        return False
    if not surface.blocks:
        return False
    try:
        push_ui_message(A2UI_SURFACE_CARD, surface.model_dump(), message=message)
    except Exception as exc:  # noqa: BLE001 — no stream / no ui channel here → skip, never crash
        log.info("present_ui.skipped", error=str(exc))
        return False
    log.info("present_ui.rendered", blocks=len(surface.blocks))
    return True


@tool
def present_ui(blocks: list[A2uiBlock], state: Annotated[dict, InjectedState] = None) -> str:
    """Render an inline UI card beside your answer. Use your JUDGMENT: reach for it when your reply is a
    clean, substantive result that genuinely reads nicer as a card than as prose, and skip it when a
    card would just be noise. Good fits:
    - You did or found a thing with details → a `fields` card (a calendar event you created, an email
      you sent, an order, a product, a task, a document).
    - A few items → a `table`. A few numbers/KPIs → `metrics` tiles.
    - A ranking, trend, or part-of-whole → a `chart`.
    Do NOT render a card for a trivial or conversational reply — a clarifying question, a yes/no, a
    quick one-liner, an apology, or an "I couldn't find anything". Just answer in words there.

    Compose an ordered list of blocks; each block sets `type` and only the fields that type uses:
    - 'heading': `text` — a short card title.
    - 'text': `text` — a sentence of context or insight.
    - 'fields': `fields` — label→value detail rows for ONE record/entity (e.g. Title / When / Where /
      Attendees for an event; From / Subject / Date for an email). Optional `title` heads the group.
      This is the go-to for "I just created/found X — show it as a card."
    - 'metrics': `metrics` — a row of KPI tiles (each: label + pre-formatted value; optional `trend`
      'up'/'down'/'neutral' with a `trend_value` like '+12%').
    - 'chart': `title`, `chart_kind` ('bar' for a ranking/comparison, 'line' for a trend over time,
      'pie' for a part-of-whole), and `series` (a list of {label, value}).
    - 'table': `columns` and `rows` (stringified cells), for a list of items. Optional `title`.

    Use it IN ADDITION to a brief written confirmation — the card supplements your prose, it doesn't
    replace it. Lead with a heading, keep it tight (2-5 blocks)."""
    # `blocks` arrive validated as A2uiBlock via the tool's args_schema, but tolerate raw dicts too.
    blocks_data = [b.model_dump() if isinstance(b, A2uiBlock) else b for b in (blocks or [])]
    push_surface(blocks_data, _last_ai_message((state or {}).get("messages", [])))
    return "Rendered an inline visual card beside your answer."


def emit_present_ui_from_messages(messages: list) -> int:
    """Re-emit any `present_ui` surfaces found in `messages` at the CURRENT graph level.

    For an IMPERATIVE node (e.g. the orchestrator's `workspace` node) whose inner tool loop runs on a
    disjoint state that never propagates its `ui` channel up, this scans the returned messages for
    `present_ui` tool-calls and re-pushes each surface — associated with the AI message that called it,
    so it renders inline under that message. Best-effort; returns how many surfaces were emitted."""
    count = 0
    for message in messages or []:
        for call in getattr(message, "tool_calls", None) or []:
            if call.get("name") == present_ui.name:
                if push_surface((call.get("args") or {}).get("blocks"), message):
                    count += 1
    return count
