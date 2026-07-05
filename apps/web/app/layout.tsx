import type { Metadata } from "next";
import { Suspense } from "react";
import { IBM_Plex_Sans, IBM_Plex_Mono } from "next/font/google";
import { NuqsAdapter } from "nuqs/adapters/next/app";
import { SessionProvider } from "next-auth/react";
import { Toaster } from "sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ThreadProvider } from "@/providers/Thread";
import { StreamProvider } from "@/providers/Stream";
import { cn } from "@/lib/utils";
import "./globals.css";

// IBM Plex Sans for interface/body, IBM Plex Mono for every number/SKU/timestamp/label.
const plexSans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-sans",
});
const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-mono",
});

export const metadata: Metadata = {
  title: "Curry Nomad — Nora",
  description: "Agent + workflow assistant for a Sri Lankan spice business (LangGraph + Aegra)",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={cn("font-sans", plexSans.variable, plexMono.variable)}
      suppressHydrationWarning
    >
      <body className="min-h-screen bg-background text-foreground antialiased">
        {/* SessionProvider (NextAuth) wraps everything so useSession works in the Stream provider and
            the workspace "Connect" affordance. Inert when auth isn't configured (session = null). */}
        <SessionProvider>
        <NuqsAdapter>
          <TooltipProvider delayDuration={0}>
            {/* ThreadProvider (Aegra thread history) + the nuqs Suspense boundary + StreamProvider
                are all hoisted here so every route shares ONE stream on ONE threadId. That's what
                lets a paused marketing run stay live across navigation (the HITL gates resume inline
                on /ask) and the sidebar "Recent" list work app-wide. StreamProvider reads threadId
                from the URL and never auto-submits, so it's inert on non-chat pages. */}
            <ThreadProvider>
              <Suspense fallback={null}>
                <StreamProvider>{children}</StreamProvider>
              </Suspense>
            </ThreadProvider>
          </TooltipProvider>
        </NuqsAdapter>
        <Toaster theme="light" richColors position="top-center" />
        </SessionProvider>
      </body>
    </html>
  );
}
