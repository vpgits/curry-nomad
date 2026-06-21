// TypeScript mirrors of the operations REST API's JSON shapes (see
// apps/nora/src/nora/operations/models.py). Kept hand-written and small — the surface is tiny.

export interface StockRow {
  product_id: number;
  sku: string;
  name: string;
  on_hand: number;
  reserved: number;
  available: number;
  reorder_point: number;
  reorder_qty: number;
  low_stock: boolean;
}

export interface OrderItem {
  product_id: number;
  sku: string;
  name: string;
  quantity: number;
  unit_price_lkr: number;
  subtotal_lkr: number;
}

export interface Order {
  order_id: number;
  customer_id: number;
  customer_name: string;
  status: string;
  total_lkr: number;
  created_at: string;
  items: OrderItem[];
  delivery_id: number | null;
}

export interface RouteStop {
  seq: number;
  delivery_id: number;
  order_id: number;
  address: string;
  city: string;
  lat: number;
  lng: number;
}

export interface RoutePlan {
  route_id: number;
  vehicle: string;
  status: string;
  total_km: number;
  naive_km: number;
  est_minutes: number;
  improvement_pct: number;
  ordered_stops: RouteStop[];
}

export interface OrderLineInput {
  sku?: string;
  product_id?: number;
  quantity: number;
}

export interface DeliveryInput {
  address: string;
  city: string;
}

// The local cities the delivery van serves (mirrors operations/geo.py:LOCAL_CITIES). Used to
// populate the delivery-city dropdown when creating an order.
export const LOCAL_CITIES = [
  "Colombo",
  "Dehiwala",
  "Moratuwa",
  "Negombo",
  "Gampaha",
  "Kandy",
  "Galle",
  "Matara",
  "Kurunegala",
  "Anuradhapura",
  "Jaffna",
] as const;

export function formatLkr(amount: number): string {
  return new Intl.NumberFormat("en-LK", { maximumFractionDigits: 0 }).format(amount) + " LKR";
}
