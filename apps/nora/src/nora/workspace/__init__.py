"""The `workspace` capability — an agent that acts on the operator's Google account.

A tool loop (like analytics) over tools exposed by the self-hosted Google Workspace MCP server.
The contrast with `routing`: routing is deterministic (the rules live in code), whereas this is
genuinely agentic — the model chooses and sequences MCP tools (send an email, then add a calendar
follow-up). Gated OFF by default (`NORA_WORKSPACE_ENABLED`); see `graph.py`.
"""
