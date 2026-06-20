import type { Metadata } from "next";
import { Inter } from "next/font/google";
import { NuqsAdapter } from "nuqs/adapters/next/app";
import { Toaster } from "sonner";
import { cn } from "@/lib/utils";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-sans" });

export const metadata: Metadata = {
  title: "Curry Nomad — Nora",
  description: "Agent + workflow assistant for a Sri Lankan spice business (LangGraph + Aegra)",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={cn("dark font-sans", inter.variable)} suppressHydrationWarning>
      <body className="min-h-screen bg-background text-foreground antialiased">
        <NuqsAdapter>{children}</NuqsAdapter>
        <Toaster theme="dark" richColors position="top-center" />
      </body>
    </html>
  );
}
