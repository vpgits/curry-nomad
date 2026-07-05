"""Offline tests for the `workspace` capability (the Google Workspace MCP agent).

Same scripted-fake approach as the other suites — no provider key, no MCP server, no network:
- a `ScriptedChatModel` drives the agent loop (tool call → final answer), and
- a fake `tools_provider` stands in for the MCP client, returning a real `@tool` the *real* ToolNode
  executes, and recording the access token it was handed (so we prove the operator's token reaches it).

The capability is OFF by default, so the optional `langchain-mcp-adapters` dependency is never
imported on the flag-off path — asserted below, which is why the whole suite stays green without the
`workspace` extra installed.
"""

from __future__ import annotations

import asyncio
import sys

import pytest
from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool, ToolException, tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from nora.config import Settings
from nora.orchestrator import build_orchestrator
from nora.workspace.graph import WORKSPACE_APPROVAL_KIND, build_workspace_agent, is_write_tool
from tests.fakes import ScriptedChatModel, ai_final, ai_tool_call


def _run(graph, *args, **kwargs):
    """Drive the (now async) orchestrator from a sync test: the workspace node is async, so the
    graph must be invoked on the async path (`ainvoke`)."""
    return asyncio.run(graph.ainvoke(*args, **kwargs))


def _stub_node(*args, **kwargs):  # noqa: ARG001 — never reached on a workspace-routed turn
    raise AssertionError("only the workspace capability should run on a workspace request")


class RecordingToolsProvider:
    """A fake `tools_provider`: records every access token it's handed and returns a single recording
    `send_email` tool, so a test can assert both that the operator's token flowed through and that the
    real ToolNode actually ran the tool."""

    def __init__(self):
        self.access_tokens: list[str] = []
        self.sent: list[dict] = []

    def __call__(self, *, access_token: str):
        self.access_tokens.append(access_token)
        sent = self.sent

        @tool
        def send_email(to: str, body: str) -> str:
            """Send an email on the operator's behalf."""
            sent.append({"to": to, "body": body})
            return f"sent to {to}"

        return [send_email]


class AsyncOnlyToolsProvider:
    """Like `RecordingToolsProvider`, but its `send_email` is a **coroutine-only** `StructuredTool` —
    a faithful stand-in for a real MCP tool, which `langchain-mcp-adapters` exposes with no sync
    implementation. Calling `.invoke()` on it raises `NotImplementedError: StructuredTool does not
    support sync invocation` (the production failure), while `.ainvoke()` works. This locks in the
    async loop (the orchestrator drives workspace via `await agent.ainvoke(...)`): a regression to a
    sync `agent.invoke(...)` would drive the tool synchronously and break, where the sync `@tool` in
    `RecordingToolsProvider` would not."""

    def __init__(self):
        self.access_tokens: list[str] = []
        self.sent: list[dict] = []

    def __call__(self, *, access_token: str):
        self.access_tokens.append(access_token)
        sent = self.sent

        async def send_email(to: str, body: str) -> str:
            sent.append({"to": to, "body": body})
            return f"sent to {to}"

        return [
            StructuredTool.from_function(
                coroutine=send_email,
                name="send_email",
                description="Send an email on the operator's behalf.",
            )
        ]


def _workspace_orch(workspace_agent):
    """Orchestrator wired to delegate to `workspace`, with stubbed analytics/marketing (never
    reached) so no provider key is needed."""
    return build_orchestrator(
        # Pin workspace_enabled=False (an explicit kwarg overrides any local .env) so the flag-off
        # default-build path is deterministic regardless of the developer's NORA_WORKSPACE_ENABLED.
        settings=Settings(workspace_enabled=False),
        # The supervisor delegates to workspace, then ends silently when it returns.
        supervisor_model=ScriptedChatModel(
            [ai_tool_call("to_workspace", {"task": "send an email"}, "h1"), ai_final("")]
        ),
        analytics_graph=_stub_node,
        marketing_graph=_stub_node,
        workspace_agent=workspace_agent,
        checkpointer=InMemorySaver(),
    )


def test_workspace_runs_the_tool_loop_with_the_operator_token():
    """Routes to workspace, runs the loop against the real ToolNode + the fake tool, and the
    operator's per-run access token reaches the tools provider."""
    model = ScriptedChatModel(
        [
            ai_tool_call(
                "send_email",
                {"to": "priya@example.com", "body": "The cloves shipment is delayed two days."},
                "call-1",
            ),
            ai_final("Sent the email to Priya about the delayed cloves shipment."),
        ]
    )
    provider = RecordingToolsProvider()
    # hitl="off": these predate the approval gate and exercise the ungated loop mechanics
    # (token flow, async tools, ToolException self-correction) — the gate is covered separately below.
    agent = build_workspace_agent(model=model, tools_provider=provider, hitl="off")
    orch = _workspace_orch(agent)

    result = _run(orch,
        {"messages": [HumanMessage("email priya that the cloves shipment is delayed")]},
        {"configurable": {"thread_id": "w-1", "google_access_token": "tok-123"}},
    )

    assert provider.access_tokens == ["tok-123"]  # the operator's token flowed to the MCP client seam
    assert provider.sent == [
        {"to": "priya@example.com", "body": "The cloves shipment is delayed two days."}
    ]  # the *real* ToolNode executed the tool the model chose
    assert "Sent the email to Priya" in result["messages"][-1].content


def test_workspace_loop_drives_async_only_mcp_tools():
    """Regression guard for the async loop: MCP tools are coroutine-only, so the loop MUST run on the
    async path (`await agent.ainvoke(...)`). A revert to a sync `agent.invoke(...)` would raise
    `NotImplementedError: StructuredTool does not support sync invocation` (it isn't a `ToolException`,
    so `handle_workspace_error` can't absorb it) — the tool would never run and `sent` would stay empty."""
    model = ScriptedChatModel(
        [
            ai_tool_call(
                "send_email",
                {"to": "priya@example.com", "body": "The cloves shipment is delayed two days."},
                "call-1",
            ),
            ai_final("Sent the email to Priya about the delayed cloves shipment."),
        ]
    )
    provider = AsyncOnlyToolsProvider()
    # hitl="off": these predate the approval gate and exercise the ungated loop mechanics
    # (token flow, async tools, ToolException self-correction) — the gate is covered separately below.
    agent = build_workspace_agent(model=model, tools_provider=provider, hitl="off")
    orch = _workspace_orch(agent)

    result = _run(orch,
        {"messages": [HumanMessage("email priya that the cloves shipment is delayed")]},
        {"configurable": {"thread_id": "w-async", "google_access_token": "tok-123"}},
    )

    # The coroutine-only tool actually executed — proves the loop ran via ainvoke, not a sync invoke.
    assert provider.sent == [
        {"to": "priya@example.com", "body": "The cloves shipment is delayed two days."}
    ]
    assert "Sent the email to Priya" in result["messages"][-1].content


def test_workspace_tool_failure_becomes_a_self_correction_message():
    """A recoverable tool failure (ToolException) is converted by the narrow handle_workspace_error
    into a ToolMessage the model reads and self-corrects from — the analytics-contrast teaching point.
    Real MCP tools raise ToolException because the provider mints them with handle_tool_errors=False
    (>=0.3.0); here a fake tool raises it directly to exercise the same ToolNode path."""

    def provider(*, access_token):  # noqa: ARG001 — token unused by the fake
        @tool
        def send_email(to: str, body: str) -> str:
            """Send an email on the operator's behalf."""
            raise ToolException("recipient address not found")

        return [send_email]

    model = ScriptedChatModel(
        [
            ai_tool_call("send_email", {"to": "bad", "body": "hi"}, "c1"),
            ai_final("I couldn't send it — the address looked wrong; can you confirm it?"),
        ]
    )
    # hitl="off": these predate the approval gate and exercise the ungated loop mechanics
    # (token flow, async tools, ToolException self-correction) — the gate is covered separately below.
    agent = build_workspace_agent(model=model, tools_provider=provider, hitl="off")
    orch = _workspace_orch(agent)

    result = _run(orch,
        {"messages": [HumanMessage("email someone")]},
        {"configurable": {"thread_id": "w-err", "google_access_token": "tok"}},
    )

    # The ToolException flowed through our handle_workspace_error → a curated ToolMessage, and the
    # model read it and produced a graceful final answer (self-correction, not a crash).
    tool_msgs = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert any("Re-read the available tools" in (m.content or "") for m in tool_msgs)
    assert "couldn't send it" in result["messages"][-1].content


# --- human-in-the-loop on write actions (path B: the hand-written loop's interrupt() gate) ---------


def _interrupt_payload(state) -> dict | None:
    """The pending interrupt's value, if the run paused (a checkpointer-backed graph returns the
    interrupt under `__interrupt__` in the result state)."""
    pending = state.get("__interrupt__")
    if not pending:
        return None
    first = pending[0]
    return getattr(first, "value", first)


def test_workspace_primitive_hitl_pauses_on_a_write_then_runs_it_on_approve():
    """The load-bearing test: an interrupt RAISED deep in the per-run-recompiled workspace subgraph
    must bubble up to pause the orchestrator, and a `Command(resume=...)` on the same thread must
    RESUME that subgraph (not restart it) so the approved write finally runs.

    The scripted model discriminates a correct resume from a broken restart: a correct resume calls
    `llm` once (propose the write → pause at the gate) then once more after resume (the final answer)
    = 2 scripted messages, with the tool running in between. A broken restart re-enters `llm` from the
    top on resume, pops the *final* message first, ends without ever running the tool → `sent` stays
    empty and this fails loudly."""
    model = ScriptedChatModel(
        [
            ai_tool_call(
                "send_email",
                {"to": "priya@example.com", "body": "The cloves shipment is delayed two days."},
                "call-1",
            ),
            ai_final("Sent the email to Priya about the delayed cloves shipment."),
        ]
    )
    provider = RecordingToolsProvider()
    # `send_email` matches the write-tool predicate (starts with "send") → it's gated.
    agent = build_workspace_agent(model=model, tools_provider=provider, hitl="primitive")
    orch = _workspace_orch(agent)
    config = {"configurable": {"thread_id": "w-hitl", "google_access_token": "tok-123"}}

    # Phase 1 — runs until the gate's interrupt. The write must NOT have executed yet.
    paused = _run(orch, {"messages": [HumanMessage("email priya the cloves are delayed")]}, config)
    payload = _interrupt_payload(paused)
    assert payload is not None, "the write should have paused the run"
    assert payload["kind"] == WORKSPACE_APPROVAL_KIND
    assert [a["name"] for a in payload["action_requests"]] == ["send_email"]
    assert provider.sent == []  # gated: nothing sent before approval

    # Phase 2 — resume with approval on the SAME thread. The subgraph resumes at the gate and runs it.
    resumed = _run(orch, Command(resume={"decisions": [{"type": "approve"}]}), config)
    assert provider.sent == [
        {"to": "priya@example.com", "body": "The cloves shipment is delayed two days."}
    ]  # the approved write ran AFTER resume — proves resume re-entered the gate, didn't restart
    assert "Sent the email to Priya" in resumed["messages"][-1].content


def test_workspace_primitive_hitl_reject_skips_the_write_and_feeds_back():
    """Rejecting a write must NOT run the tool; instead a synthetic ToolMessage tells the model the
    operator declined, and the model self-corrects into a graceful reply."""
    model = ScriptedChatModel(
        [
            ai_tool_call("send_email", {"to": "priya@example.com", "body": "delayed"}, "call-1"),
            ai_final("Okay, I won't send it. Let me know if you'd like to revise and try again."),
        ]
    )
    provider = RecordingToolsProvider()
    agent = build_workspace_agent(model=model, tools_provider=provider, hitl="primitive")
    orch = _workspace_orch(agent)
    config = {"configurable": {"thread_id": "w-reject", "google_access_token": "tok"}}

    paused = _run(orch, {"messages": [HumanMessage("email priya")]}, config)
    assert _interrupt_payload(paused)["kind"] == WORKSPACE_APPROVAL_KIND

    resumed = _run(
        orch,
        Command(resume={"decisions": [{"type": "reject", "message": "Not now."}]}),
        config,
    )
    assert provider.sent == []  # rejected: the tool never ran
    # the rejection became a ToolMessage the model read, then answered gracefully
    tool_msgs = [m for m in resumed["messages"] if isinstance(m, ToolMessage)]
    assert any("Not now." in (m.content or "") for m in tool_msgs)
    assert "won't send it" in resumed["messages"][-1].content


# --- human-in-the-loop on write actions (path A: create_agent + HumanInTheLoopMiddleware) ----------


def test_workspace_middleware_hitl_pauses_then_resumes_on_approve():
    """The contrast path: the SAME pause/resume behaviour, but produced by the prebuilt
    `create_agent` + `HumanInTheLoopMiddleware` instead of the hand-written gate. Proves the
    orchestrator node and the `{"decisions": [...]}` resume protocol don't care which mechanism is
    active — and pins the middleware's actual interrupt payload shape (`action_requests`)."""
    model = ScriptedChatModel(
        [
            ai_tool_call(
                "send_email",
                {"to": "priya@example.com", "body": "The cloves shipment is delayed two days."},
                "call-1",
            ),
            ai_final("Sent the email to Priya about the delayed cloves shipment."),
        ]
    )
    provider = RecordingToolsProvider()
    agent = build_workspace_agent(model=model, tools_provider=provider, hitl="middleware")
    orch = _workspace_orch(agent)
    config = {"configurable": {"thread_id": "w-mw", "google_access_token": "tok-9"}}

    paused = _run(orch, {"messages": [HumanMessage("email priya the cloves are delayed")]}, config)
    payload = _interrupt_payload(paused)
    assert payload is not None, "the middleware should have paused on the write"
    # The middleware's payload carries `action_requests` (no `kind`); the web client detects either it
    # or path B's `kind == workspace_approval`. The gated tool appears among the requested actions.
    names = [a.get("name") or a.get("action") for a in payload["action_requests"]]
    assert "send_email" in names
    assert provider.sent == []  # gated by the middleware: nothing sent before approval

    resumed = _run(orch, Command(resume={"decisions": [{"type": "approve"}]}), config)
    assert provider.sent == [
        {"to": "priya@example.com", "body": "The cloves shipment is delayed two days."}
    ]  # the middleware ran the approved write on resume — same single `{decisions:[...]}` protocol
    assert "Sent the email to Priya" in resumed["messages"][-1].content


def test_workspace_middleware_hitl_self_corrects_on_tool_error():
    """Regression for the create_agent/middleware path: a recoverable ToolException from an APPROVED
    write must self-correct (become a curated ToolMessage the model repairs) — NOT propagate out of
    the agent and degrade the turn. Without the `_self_correcting` tool wrapper this fails: the raise
    escapes `create_agent` + `HumanInTheLoopMiddleware`, the orchestrator's `except` catches it, and
    the operator gets a generic 'couldn't reach Workspace' reply instead of a graceful answer."""

    def provider(*, access_token):  # noqa: ARG001 — token unused by the fake
        @tool
        def send_email(to: str, body: str) -> str:
            """Send an email on the operator's behalf."""
            raise ToolException("recipient address not found")

        return [send_email]

    model = ScriptedChatModel(
        [
            ai_tool_call("send_email", {"to": "bad", "body": "hi"}, "c1"),
            ai_final("I couldn't send it — the address looked wrong; can you confirm it?"),
        ]
    )
    agent = build_workspace_agent(model=model, tools_provider=provider, hitl="middleware")
    orch = _workspace_orch(agent)
    config = {"configurable": {"thread_id": "w-mw-err", "google_access_token": "tok"}}

    _run(orch, {"messages": [HumanMessage("email someone")]}, config)  # pauses at the gate
    resumed = _run(orch, Command(resume={"decisions": [{"type": "approve"}]}), config)

    # The ToolException became a self-correction ToolMessage (not a propagated crash) and the model
    # answered gracefully — proves the middleware path keeps the self-correcting loop.
    tool_msgs = [m for m in resumed["messages"] if isinstance(m, ToolMessage)]
    assert any("Re-read the available tools" in (m.content or "") for m in tool_msgs)
    assert "couldn't send it" in resumed["messages"][-1].content


# --- write-gate coverage (audit regressions) ------------------------------------------------------


def test_is_write_tool_gates_the_manage_convention_writes():
    """Audit regression: this MCP server names its multi-mode create/update/delete tools `manage_*`
    (plus `format_*`/`resize_*`/`export_doc_to_pdf`), which the verb list originally missed — so those
    12 real WRITE tools ran with NO approval gate. They must all be gated now, and no READ tool may be
    caught by the added verbs."""
    must_gate = [
        "manage_event", "manage_task", "manage_task_list", "manage_gmail_label",
        "manage_out_of_office", "manage_focus_time", "manage_drive_access", "manage_doc_tab",
        "manage_conditional_formatting", "format_sheet_range", "resize_sheet_dimensions",
        "export_doc_to_pdf",
    ]
    must_not_gate = [
        "list_events", "get_event", "search_gmail_messages", "list_tasks", "get_doc_content",
        "list_calendars", "get_gmail_thread", "list_drive_items", "get_drive_file_content",
    ]
    ungated_writes = [t for t in must_gate if not is_write_tool(t)]
    assert ungated_writes == [], f"these writes bypass the approval gate: {ungated_writes}"
    over_gated_reads = [t for t in must_not_gate if is_write_tool(t)]
    assert over_gated_reads == [], f"these reads are wrongly gated: {over_gated_reads}"


def test_build_workspace_agent_fails_closed_on_an_unknown_hitl_mode():
    """Audit regression: an unrecognized HITL mode must FAIL LOUD, never silently fall through to the
    ungated loop (which would disable write approval account-wide on a typo). Only off/primitive/
    middleware are valid."""
    agent = build_workspace_agent(
        model=ScriptedChatModel([ai_final("hi")]),
        tools_provider=RecordingToolsProvider(),
        hitl="bogus",
    )
    with pytest.raises(ValueError, match="unknown workspace_hitl mode"):
        asyncio.run(agent([HumanMessage("hi")], access_token="tok"))


def test_workspace_middleware_edit_cannot_swap_the_tool_name():
    """Audit regression (CRITICAL, default `middleware` path): an `edit` decision may change a pending
    write's ARGS but must NEVER change its tool NAME. A crafted resume that swaps the reviewed
    `send_email` for a never-shown `delete_everything` is clamped — the reviewed tool runs (with the
    edited args) and the swapped-in tool never executes."""

    class _TwoWriteProvider:
        def __init__(self):
            self.sent: list[dict] = []
            self.deleted: list[dict] = []

        def __call__(self, *, access_token):  # noqa: ARG002 — token unused by the fake
            sent, deleted = self.sent, self.deleted

            @tool
            def send_email(to: str, body: str) -> str:
                """Send an email on the operator's behalf."""
                sent.append({"to": to, "body": body})
                return f"sent to {to}"

            @tool
            def delete_everything(to: str, body: str) -> str:
                """Irreversibly delete the operator's data."""
                deleted.append({"to": to, "body": body})
                return "deleted"

            return [send_email, delete_everything]

    model = ScriptedChatModel(
        [
            ai_tool_call("send_email", {"to": "priya@example.com", "body": "delayed"}, "call-1"),
            ai_final("Done."),
        ]
    )
    provider = _TwoWriteProvider()
    agent = build_workspace_agent(model=model, tools_provider=provider, hitl="middleware")
    orch = _workspace_orch(agent)
    config = {"configurable": {"thread_id": "w-edit-swap", "google_access_token": "tok"}}

    paused = _run(orch, {"messages": [HumanMessage("email priya")]}, config)
    assert _interrupt_payload(paused) is not None  # paused on the send_email write

    # Malicious resume: "approve" as an EDIT but swap the tool to delete_everything.
    resumed = _run(
        orch,
        Command(
            resume={
                "decisions": [
                    {
                        "type": "edit",
                        "edited_action": {
                            "name": "delete_everything",
                            "args": {"to": "priya@example.com", "body": "delayed"},
                        },
                    }
                ]
            }
        ),
        config,
    )

    assert provider.deleted == []  # the swapped-in tool NEVER ran
    assert provider.sent == [{"to": "priya@example.com", "body": "delayed"}]  # reviewed tool ran (clamped)
    assert resumed is not None


# --- AI-authored approval layout (presentation by the model, values stay literal) -----------------


def test_author_approval_layout_keeps_values_literal_and_hides_nothing():
    """The model authors the LAYOUT (icon/title/labels/order via arg_keys); code fills each value from
    the LITERAL args — the model never supplies the text, so the approver sees exactly what will run.
    An arg the layout omits is still appended (nothing that will be sent is hidden)."""
    from nora.schemas import ApprovalField, ApprovalLayout
    from nora.workspace.graph import _author_approval_layout

    class _FakeLayoutModel:
        def with_structured_output(self, schema):
            assert schema is ApprovalLayout

            class _Runnable:
                async def ainvoke(self, _messages):
                    return ApprovalLayout(
                        icon="email",
                        title="Draft email",
                        fields=[
                            ApprovalField(label="To", arg_key="to"),
                            ApprovalField(label="Body", arg_key="body", style="block"),
                        ],
                    )

            return _Runnable()

    args = {"to": "a@b.com", "subject": "Hi", "body": "A long body of text"}
    layout = asyncio.run(_author_approval_layout(_FakeLayoutModel(), "draft_gmail_message", args))

    assert layout["icon"] == "email" and layout["title"] == "Draft email"
    by_label = {f["label"]: f for f in layout["fields"]}
    assert by_label["To"]["value"] == "a@b.com"  # literal arg — the model only named the key
    assert by_label["Body"]["value"] == "A long body of text" and by_label["Body"]["style"] == "block"
    assert by_label["Subject"]["value"] == "Hi"  # uncovered arg appended → nothing hidden from approver


def test_author_approval_layout_is_none_without_a_model():
    """No layout model (the middleware path, or no provider key) → None, and the web client renders its
    own literal fallback card. Best-effort, so offline tests need no key."""
    from nora.workspace.graph import _author_approval_layout

    assert asyncio.run(_author_approval_layout(None, "send_gmail_message", {"to": "x@y.com"})) is None


def test_workspace_degrades_without_a_token():
    """No per-run Google token (operator hasn't connected) → a friendly 'connect' reply, no crash,
    and the agent/tools are never invoked."""
    provider = RecordingToolsProvider()
    agent = build_workspace_agent(model=ScriptedChatModel([]), tools_provider=provider)
    orch = _workspace_orch(agent)

    result = _run(orch,
        {"messages": [HumanMessage("email priya the shipment is delayed")]},
        {"configurable": {"thread_id": "w-2"}},  # no google_access_token
    )

    assert "connect your google workspace" in result["messages"][-1].content.lower()
    assert provider.access_tokens == []  # the agent must not run without a token


def test_workspace_disabled_does_not_import_mcp():
    """Flag OFF (workspace_agent=None) → delegating to workspace still yields the 'connect' reply via
    the sync stub node, and never imports langchain-mcp-adapters. The adapter is a base dependency now
    (workspace is first-party), but the flag-off path must stay lazy — turning workspace off keeps the
    import out of the hot path / startup."""
    orch = _workspace_orch(None)  # workspace_agent=None + workspace_enabled=False → the sync stub

    result = _run(orch,
        {"messages": [HumanMessage("send an email for me")]},
        {"configurable": {"thread_id": "w-3", "google_access_token": "tok-123"}},
    )

    assert "connect your google workspace" in result["messages"][-1].content.lower()
    # Flag-off path must not import the MCP adapter even though it's installed (lazy-import discipline).
    assert "langchain_mcp_adapters" not in sys.modules


def test_workspace_first_party_default_wires_the_async_node():
    """The SHIPPED default (workspace_enabled=True) builds the real async workspace node without a
    provider key (the model is built lazily) and, with no per-run Google token, degrades to the
    'connect' reply — proving the first-party default is wired (no agent injected, no MCP server,
    no key)."""
    orch = build_orchestrator(
        # The shipped default; the offline suite pins it OFF (conftest), so set it explicitly here.
        settings=Settings(workspace_enabled=True),
        supervisor_model=ScriptedChatModel(
            [ai_tool_call("to_workspace", {"task": "email someone"}, "h1"), ai_final("")]
        ),
        analytics_graph=_stub_node,
        marketing_graph=_stub_node,
        checkpointer=InMemorySaver(),
    )
    # No google_access_token → connect-degrade; the real agent never runs, so no MCP call/import.
    result = _run(orch,
        {"messages": [HumanMessage("email someone")]},
        {"configurable": {"thread_id": "w-fp"}},
    )
    assert "connect your google workspace" in result["messages"][-1].content.lower()


def test_workspace_agent_present_ui_is_reemitted_to_top_level():
    """The workspace agent can author a generative-UI card mid-answer via present_ui. Because the node
    is IMPERATIVE — its inner loop's `ui` channel is discarded, only the messages are returned — the
    card can't propagate up on its own (unlike the analytics subgraph). The orchestrator's workspace
    node RE-EMITS it (emit_present_ui_from_messages), so it lands in the top-level `ui` channel bound to
    the AI message that authored it. present_ui is a read-like local tool (never gated), so hitl='off'
    exercises the plain ToolNode path here."""
    model = ScriptedChatModel(
        [
            ai_tool_call(
                "present_ui",
                {
                    "blocks": [
                        {"type": "heading", "text": "Unread from suppliers"},
                        {
                            "type": "table",
                            "columns": ["From", "Subject"],
                            "rows": [["priya@matale.lk", "Cloves ETA"]],
                        },
                    ]
                },
                "c1",
            ),
            ai_final("You have 1 unread supplier email."),
        ]
    )
    agent = build_workspace_agent(model=model, tools_provider=lambda *, access_token: [], hitl="off")
    orch = _workspace_orch(agent)

    result = _run(orch,
        {"messages": [HumanMessage("summarize my unread supplier emails")]},
        {"configurable": {"thread_id": "w-present-ui", "google_access_token": "tok"}},
    )

    cards = [u for u in result.get("ui", []) if u.get("name") == "a2ui_surface"]
    assert len(cards) == 1, "the workspace-authored surface must be re-emitted exactly once at top level"
    assert [b["type"] for b in cards[0]["props"]["blocks"]] == ["heading", "table"]
    # Bound to the AI message that called present_ui (so it renders inline under it).
    author_id = cards[0]["metadata"]["message_id"]
    assert author_id and any(getattr(m, "id", None) == author_id for m in result["messages"])
