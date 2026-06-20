import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Curry Nomad — Nora",
  description: "Agent + workflow assistant for a Sri Lankan spice business (LangGraph + Aegra)",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
