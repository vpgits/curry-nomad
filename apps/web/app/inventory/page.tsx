import { redirect } from "next/navigation";

// The operations console was split into dedicated /stock and /orders routes (each its own sidebar
// item + header). Keep /inventory as a permanent redirect to the first of them.
export default function InventoryPage() {
  redirect("/stock");
}
