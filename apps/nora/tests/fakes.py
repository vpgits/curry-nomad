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


# A minimal valid-enough PNG payload (the renderer only writes bytes to disk; it never decodes them).
_FAKE_PNG = b"\x89PNG\r\n\x1a\nfake-image-bytes"


class FakeOpenRouterClient:
    """Duck-typed `OpenRouterClient` for offline renderer tests: returns canned image bytes and
    fake video job ids, and records every call so tests can assert what was sent (e.g. whether a
    first-frame URL was passed → image→video vs text→video)."""

    def __init__(self):
        self.image_calls: list[dict] = []
        self.video_calls: list[dict] = []

    def generate_image(self, *, model: str, prompt: str, aspect_ratio: str) -> bytes:
        self.image_calls.append({"model": model, "prompt": prompt, "aspect_ratio": aspect_ratio})
        return _FAKE_PNG

    def submit_video(self, *, model, prompt, first_frame_url, duration_s, resolution,
                     aspect_ratio, generate_audio) -> dict:
        self.video_calls.append(
            {"model": model, "prompt": prompt, "first_frame_url": first_frame_url,
             "duration_s": duration_s, "resolution": resolution, "aspect_ratio": aspect_ratio,
             "generate_audio": generate_audio}
        )
        return {"id": f"job-{len(self.video_calls)}", "status": "pending",
                "polling_url": f"/api/v1/videos/job-{len(self.video_calls)}"}

    def get_video(self, job_id: str) -> dict:
        return {"id": job_id, "status": "completed",
                "unsigned_urls": [f"/api/v1/videos/{job_id}/content?index=0"]}
