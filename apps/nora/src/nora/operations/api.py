"""The operations REST API — a thin HTTP layer over the services.

Deliberately thin: every route parses the request, calls the matching ``services.*`` function,
and returns its result as JSON. No business logic lives here — it all lives in ``services.py`` —
so when Phase 2 wraps those same functions as agent tools, the rules come along for free.

Rejections raise ``OperationsError`` in the service; a single exception handler turns that into a
structured ``{"error": "<message>"}`` with a ``409`` (business-rule conflict, e.g. an oversell).
Lookups of a specific id that miss return ``404`` with the same shape. The web `/inventory` page
is the only client today; CORS is opened for the Next.js dev origin.

Run:  ``uv run --extra operations uvicorn nora.operations.api:app --port 8000``  (or ``nora-ops-api``).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from nora.config import get_settings
from nora.operations import services
from nora.operations.errors import OperationsError
from nora.operations.interfaces import OperationsStore
from nora.operations.models import as_dict
from nora.operations.services import DeliveryInput, OrderLineInput
from nora.operations.store import build_operations_store

app = FastAPI(title="Nora Operations", version="1.0.0")

# The web /inventory page runs on :3000 in dev. (No credentials/cookies — a plain read+write API.)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(OperationsError)
async def _operations_error_handler(_request: Request, exc: OperationsError) -> JSONResponse:
    """Every rejected mutation becomes a 409 carrying the service's message verbatim."""
    return JSONResponse(status_code=409, content={"error": str(exc)})


# Serve generated marketing media (hero image + per-shot stills written by the OpenRouter renderer)
# at /media. The renderer (in the nora graph) and this service share `settings.media_dir` — the same
# repo dir locally, a shared volume in Docker. Static files only: no LLM, no OpenRouter key here, so
# the ops service stays keyless. The dir is created if absent (renders may not have run yet).
_media_dir = get_settings().media_dir
_media_dir.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=str(_media_dir)), name="media")


def get_store() -> OperationsStore:
    """Dependency: the operations store. Overridden in tests to point at a disposable DB."""
    return build_operations_store(get_settings())


# The store, injected per request. Annotated form (not a `= Depends(...)` default) so it composes
# with optional query params and keeps the linter happy.
StoreDep = Annotated[OperationsStore, Depends(get_store)]


# --- request bodies -------------------------------------------------------------------------

class ReceiveBody(BaseModel):
    product_id: int
    qty: int
    reason: str | None = None
    idempotency_key: str | None = None


class AdjustBody(BaseModel):
    product_id: int
    qty_delta: int
    reason: str
    kind: str = "adjust"


class OrderLineBody(BaseModel):
    quantity: int
    product_id: int | None = None
    sku: str | None = None


class DeliveryBody(BaseModel):
    address: str
    city: str
    lat: float | None = None
    lng: float | None = None
    window_start: str | None = None
    window_end: str | None = None


class CreateOrderBody(BaseModel):
    customer_id: int
    lines: list[OrderLineBody]
    delivery: DeliveryBody | None = None
    idempotency_key: str | None = None


class PlanRouteBody(BaseModel):
    vehicle: str = "van-1"


# --- routes ---------------------------------------------------------------------------------

@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/stock")
def get_stock(store: StoreDep) -> list[dict]:
    return [as_dict(s) for s in services.list_stock(store)]


@app.get("/stock/low")
def get_low_stock(store: StoreDep) -> list[dict]:
    return [as_dict(s) for s in services.list_low_stock(store)]


@app.post("/stock/receive")
def post_receive(body: ReceiveBody, store: StoreDep) -> dict:
    row = services.receive_stock(
        store, body.product_id, body.qty,
        reason=body.reason, idempotency_key=body.idempotency_key,
    )
    return as_dict(row)


@app.post("/stock/adjust")
def post_adjust(body: AdjustBody, store: StoreDep) -> dict:
    row = services.adjust_stock(
        store, body.product_id, body.qty_delta, reason=body.reason, kind=body.kind,
    )
    return as_dict(row)


@app.get("/ledger")
def get_ledger(store: StoreDep, product_id: int | None = None) -> list[dict]:
    return [as_dict(e) for e in services.get_ledger(store, product_id=product_id)]


@app.post("/orders")
def post_order(body: CreateOrderBody, store: StoreDep) -> dict:
    lines = [
        OrderLineInput(quantity=line.quantity, product_id=line.product_id, sku=line.sku)
        for line in body.lines
    ]
    delivery = (
        DeliveryInput(
            address=body.delivery.address,
            city=body.delivery.city,
            lat=body.delivery.lat,
            lng=body.delivery.lng,
            window_start=body.delivery.window_start,
            window_end=body.delivery.window_end,
        )
        if body.delivery is not None
        else None
    )
    order = services.create_order(
        store, body.customer_id, lines,
        delivery=delivery, idempotency_key=body.idempotency_key,
    )
    return as_dict(order)


@app.get("/orders")
def get_orders(store: StoreDep, status: str | None = None) -> list[dict]:
    return [as_dict(o) for o in services.list_orders(store, status=status)]


@app.get("/orders/{order_id}", response_model=None)
def get_order(order_id: int, store: StoreDep) -> JSONResponse | dict:
    try:
        return as_dict(services.get_order(store, order_id))
    except OperationsError as exc:
        return JSONResponse(status_code=404, content={"error": str(exc)})


@app.post("/routes/plan")
def post_plan_route(body: PlanRouteBody, store: StoreDep) -> dict:
    return as_dict(services.plan_route(store, vehicle=body.vehicle))


@app.get("/routes/{route_id}", response_model=None)
def get_route(route_id: int, store: StoreDep) -> JSONResponse | dict:
    try:
        return as_dict(services.get_route(store, route_id))
    except OperationsError as exc:
        return JSONResponse(status_code=404, content={"error": str(exc)})


@app.post("/routes/{route_id}/dispatch")
def post_dispatch_route(route_id: int, store: StoreDep) -> dict:
    return as_dict(services.dispatch_route(store, route_id))


def run() -> None:
    """Console-script entry point (`nora-ops-api`): serve the API on :8000."""
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    run()
