import type { Metadata } from "next";
import { Suspense } from "react";
import { Inter } from "next/font/google";
import { NuqsAdapter } from "nuqs/adapters/next/app";
import { Toaster } from "sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ThreadProvider } from "@/providers/Thread";
import { cn } from "@/lib/utils";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-sans" });

export const metadata: Metadata = {
  title: "Curry Nomad — Nora",
  description: "Agent + workflow assistant for a Sri Lankan spice business (LangGraph)",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={cn("dark font-sans", inter.variable)} suppressHydrationWarning>
      <body className="min-h-screen bg-background text-foreground antialiased">
        <NuqsAdapter>
          <TooltipProvider delayDuration={0}>
            {/* ThreadProvider (thread history) + a Suspense boundary for the sidebar's
                nuqs threadId state are shared by every page so the AppShell sidebar works app-wide. */}
            <ThreadProvider>
              <Suspense fallback={null}>{children}</Suspense>
            </ThreadProvider>
          </TooltipProvider>
        </NuqsAdapter>
        <Toaster theme="dark" richColors position="top-center" />
      </body>
    </html>
  );
}
