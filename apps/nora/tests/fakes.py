"""Test doubles.

`ScriptedChatModel` is a minimal stand-in for a chat model: it ignores its input and returns
a pre-scripted sequence of AIMessages. That's enough to drive the analytics agent loop offline
(no API key) — including the self-correction path: script a bad-SQL tool call, then a
corrected one, then a final answer, and the real ToolNode + SpiceDB do the rest.
"""

from __future__ import annotations

import threading

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
        self.last_messages: list = []  # captured for prompt assertions

    def bind_tools(self, tools, **kwargs):  # noqa: ARG002 - signature parity only
        return self

    def invoke(self, messages, config=None, **kwargs):  # noqa: ARG002
        self.last_messages = list(messages)
        if self._i >= len(self._messages):
            raise AssertionError("ScriptedChatModel ran out of scripted responses")
        msg = self._messages[self._i]
        self._i += 1
        return msg


class _StructuredRunnable:
    """What `.with_structured_output(Schema)` returns: `.invoke(...)` pops the next scripted
    object of that schema from the parent."""

    def __init__(self, parent: ScriptedStructuredModel, schema):
        self._parent = parent
        self._schema = schema

    def invoke(self, prompt, config=None, **kwargs):  # noqa: ARG002
        self._parent.record_prompt(str(prompt))
        return self._parent._next(self._schema)


class ScriptedStructuredModel:
    """A fake model for the marketing workflow.

    - `.with_structured_output(Schema).invoke(...)` returns the next scripted object for that
      schema (thread-safe; ideation runs workers in parallel).
    - `.invoke(...)` returns a plain AIMessage (used for free-text shot prompts).

    Queues "repeat the last item" once down to a single entry, so loop iterations and parallel
    fan-outs don't run the script dry — tests assert on structure, not scripted identity.
    """

    def __init__(self, by_type: dict, shot_text: str = "A warm cinematic Sri Lankan kitchen."):
        self._by_type = {k: list(v) for k, v in by_type.items()}
        self._shot_text = shot_text
        self._lock = threading.Lock()
        self.prompts: list[str] = []  # captured for prompt assertions

    def record_prompt(self, text: str) -> None:
        with self._lock:
            self.prompts.append(text)

    def bind_tools(self, tools, **kwargs):  # noqa: ARG002
        return self

    def with_structured_output(self, schema, **kwargs):  # noqa: ARG002
        return _StructuredRunnable(self, schema)

    def invoke(self, prompt, config=None, **kwargs):  # noqa: ARG002
        return AIMessage(content=self._shot_text)

    def _next(self, schema):
        with self._lock:
            queue = self._by_type.get(schema)
            if not queue:
                raise AssertionError(f"no scripted response for {getattr(schema, '__name__', schema)}")
            return queue.pop(0) if len(queue) > 1 else queue[0]
