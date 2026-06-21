"""The operations layer's single, typed error.

Every rejected mutation — an oversell, a write-off that would drive stock below zero, an
unknown SKU — raises ``OperationsError`` with a message written for a human (and, in Phase 2,
for the agent to read and self-correct from). This is the deliberate analogue of
``services.interfaces.SqlError``: a narrow, intentional exception the callers above (the REST
API now, a ``ToolNode`` self-correction loop later) can catch and translate, while any *other*
exception is a real bug and fails loud.
"""

from __future__ import annotations


class OperationsError(Exception):
    """Raised by the operations services for any rejected or invalid request.

    The message carries the business-rule violation verbatim (e.g. ``"cannot reserve 200 of
    CIN-ALBA-100: only 40 available"``). The REST layer turns it into a structured 4xx; the
    Phase-2 agent tool will turn it into a ToolMessage so the model can retry with a fix.
    """
