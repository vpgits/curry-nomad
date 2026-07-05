// Typed fetch client for the operations REST API. Every call surfaces the API's structured
// `{ "error": "..." }` message on failure so the UI can toast it verbatim — the same business-rule
// message the (future) agent would read and self-correct from.

import { OPS_API_URL } from "@/lib/config";
import type { DeliveryInput, Order, OrderLineInput, StockRow } from "@/lib/ops-types";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${OPS_API_URL}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...init,
    });
  } catch {
    throw new Error(
      `Can't reach the operations API at ${OPS_API_URL}. Is it running? ` +
        `(uv run --extra operations uvicorn nora.operations.api:app --port 8000)`,
    );
  }
  if (!res.ok) {
    let message = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (body?.error) message = body.error;
    } catch {
      /* non-JSON error body — keep the status message */
    }
    throw new Error(message);
  }
  return res.json() as Promise<T>;
}

export const ops = {
  getStock: () => req<StockRow[]>("/stock"),
  getLowStock: () => req<StockRow[]>("/stock/low"),

  receiveStock: (body: { product_id: number; qty: number; reason?: string }) =>
    req<StockRow>("/stock/receive", { method: "POST", body: JSON.stringify(body) }),

  adjustStock: (body: { product_id: number; qty_delta: number; reason: string; kind?: string }) =>
    req<StockRow>("/stock/adjust", { method: "POST", body: JSON.stringify(body) }),

  createOrder: (body: {
    customer_id: number;
    lines: OrderLineInput[];
    delivery?: DeliveryInput;
  }) => req<Order>("/orders", { method: "POST", body: JSON.stringify(body) }),

  listOrders: () => req<Order[]>("/orders"),
};
