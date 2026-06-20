"""Test doubles.

`ScriptedChatModel` is a minimal stand-in for a chat model: it ignores its input and returns
a pre-scripted sequence of AIMessages. That's enough to drive the analytics agent loop offline
(no API key) — including the self-correction path: script a bad-SQL tool call, then a
corrected one, then a final answer, and the real ToolNode + SpiceDB do the rest.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage


def ai_tool_call(name: str, args: dict, call_id: str) -> AIMessage:
    """An AIMessage that requests a single tool call."""
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}],
    )


def ai_final(text: str) -> AIMessage:
    """An AIMessage with no tool calls (ends the loop)."""
    return AIMessage(content=text)


class ScriptedChatModel:
    """Duck-typed chat model: `.bind_tools(...)` returns self; each `.invoke(...)` pops the
    next scripted message. Raises if the script runs out (catches runaway loops in tests)."""

    def __init__(self, messages: list[AIMessage]):
        self._messages = list(messages)
        self._i = 0

    def bind_tools(self, tools, **kwargs):  # noqa: ARG002 - signature parity only
        return self

    def invoke(self, messages, config=None, **kwargs):  # noqa: ARG002
        if self._i >= len(self._messages):
            raise AssertionError("ScriptedChatModel ran out of scripted responses")
        msg = self._messages[self._i]
        self._i += 1
        return msg
