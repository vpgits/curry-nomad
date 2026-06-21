"""End-to-end-ish tests of the REST layer via Starlette's TestClient.

Needs the `operations` extra (fastapi + httpx); skipped cleanly otherwise, the same way the
langfuse tests are gated — the base offline suite never requires it.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")  # Starlette's TestClient transport

from fastapi.testclient import TestClient  # noqa: E402

from nora.operations.api import app, get_store  # noqa: E402


@pytest.fixture
def client(ops_store):
    app.dependency_overrides[get_store] = lambda: ops_store
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _pid(ops_store, sku: str) -> int:
    return ops_store.fetch_one("SELECT product_id FROM ref_products WHERE sku = ?", (sku,))[
        "product_id"
    ]


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_get_stock_and_low(client):
    stock = client.get("/stock").json()
    assert isinstance(stock, list) and stock
    assert {"sku", "on_hand", "reserved", "available", "low_stock"} <= set(stock[0])
    low = client.get("/stock/low").json()
    assert all(item["low_stock"] for item in low)


def test_receive_increments(client, ops_store):
    pid = _pid(ops_store, "CIN-ALBA-100")
    before = client.get("/stock").json()
    on_hand = next(s["on_hand"] for s in before if s["product_id"] == pid)
    r = client.post("/stock/receive", json={"product_id": pid, "qty": 25})
    assert r.status_code == 200
    assert r.json()["on_hand"] == on_hand + 25


def test_create_order_happy_path(client):
    r = client.post(
        "/orders",
        json={"customer_id": 1, "lines": [{"sku": "CIN-ALBA-100", "quantity": 2}]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "reserved"
    assert body["total_lkr"] > 0


def test_oversell_returns_409_with_error_message(client, ops_store):
    pid = _pid(ops_store, "CIN-ALBA-100")
    available = next(
        s["available"] for s in client.get("/stock").json() if s["product_id"] == pid
    )
    r = client.post(
        "/orders",
        json={"customer_id": 1, "lines": [{"sku": "CIN-ALBA-100", "quantity": available + 1}]},
    )
    assert r.status_code == 409
    assert "available" in r.json()["error"]


def test_write_off_below_zero_returns_409(client, ops_store):
    pid = _pid(ops_store, "CIN-ALBA-100")
    on_hand = next(s["on_hand"] for s in client.get("/stock").json() if s["product_id"] == pid)
    r = client.post(
        "/stock/adjust",
        json={"product_id": pid, "qty_delta": -(on_hand + 1), "reason": "flood"},
    )
    assert r.status_code == 409
    assert "error" in r.json()


def test_plan_and_dispatch_route(client):
    plan = client.post("/routes/plan", json={}).json()
    assert plan["status"] == "planned"
    assert plan["total_km"] <= plan["naive_km"]
    assert len(plan["ordered_stops"]) == 8

    dispatched = client.post(f"/routes/{plan['route_id']}/dispatch").json()
    assert dispatched["status"] == "dispatched"


def test_unknown_order_returns_404(client):
    r = client.get("/orders/999999")
    assert r.status_code == 404
    assert "error" in r.json()
