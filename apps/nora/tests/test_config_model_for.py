"""Per-node model resolution (`Settings.model_for`).

Each capability node can run its own `provider:model` string; when its override is empty it falls
back to the base `model`. The supervisor is intentionally NOT covered here — it uses `router_model`.
"""

from __future__ import annotations

from nora.config import Settings

NODES = ["analytics", "marketing", "workspace", "dashboard"]


def test_model_for_falls_back_to_base_model_when_unset():
    s = Settings(model="openai:gpt-5.4-mini")
    for node in NODES:
        assert s.model_for(node) == "openai:gpt-5.4-mini"


def test_model_for_uses_override_when_set():
    s = Settings(
        model="openai:gpt-5.4-mini",
        analytics_model="openai:gpt-5.4",
        marketing_model="anthropic:claude-sonnet-4-6",
    )
    assert s.model_for("analytics") == "openai:gpt-5.4"
    assert s.model_for("marketing") == "anthropic:claude-sonnet-4-6"
    # Unset nodes still fall back to the base model.
    assert s.model_for("workspace") == "openai:gpt-5.4-mini"
    assert s.model_for("dashboard") == "openai:gpt-5.4-mini"


def test_supervisor_is_configured_separately_from_model_for():
    # The orchestrator/supervisor knob is `router_model`, independent of the base `model` and the
    # per-node overrides — so the non-orchestrator default and the supervisor can differ.
    s = Settings(model="openai:gpt-5.4-mini", router_model="openai:gpt-5.4")
    assert s.router_model == "openai:gpt-5.4"
    assert all(s.model_for(node) == "openai:gpt-5.4-mini" for node in NODES)
