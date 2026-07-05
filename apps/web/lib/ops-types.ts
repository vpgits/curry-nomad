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

// Built once at module scope — `new Intl.NumberFormat` reloads locale-data tables on every call, so
// rebuilding it per format() (and per list item) is wasted work.
const LKR_NUMBER_FORMAT = new Intl.NumberFormat("en-LK", { maximumFractionDigits: 0 });

// "₨ 4,250" — the redesign's rupee format (₨ prefix, no decimals).
export function formatRupees(amount: number): string {
  return "₨ " + LKR_NUMBER_FORMAT.format(amount);
}

// "₨ 1.28M" / "₨ 96k" — compact form for KPI hero numbers.
export function formatRupeesShort(amount: number): string {
  const abs = Math.abs(amount);
  if (abs >= 1_000_000) return "₨ " + (amount / 1_000_000).toFixed(2).replace(/\.?0+$/, "") + "M";
  if (abs >= 1_000) return "₨ " + Math.round(amount / 1_000) + "k";
  return "₨ " + amount;
}
