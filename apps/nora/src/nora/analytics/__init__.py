"""Analytics — the AGENT.

An open-ended SQL tool loop: the model inspects the schema, writes a query, runs it, and
*self-corrects* when the query fails (the DB error comes back as a ToolMessage). This is the
"why an agent, not a fixed pipeline" lesson.
"""
