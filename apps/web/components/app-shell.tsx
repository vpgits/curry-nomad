"use client";

import type { CSSProperties, ReactNode } from "react";

import { AppSidebar } from "@/components/app-sidebar";
import { AskNoraBar } from "@/components/AskNoraBar";
import { SidebarInset, SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";

// The app shell shared by every page: the fixed 212px AppSidebar plus a SidebarInset hosting the
// shared header (per-screen title/subtitle + the global "Ask Nora" bar) and the page body. The body
// `children` are direct flex children of the inset column, so a page can pin a footer / scroll
// region with `flex-1` / `shrink-0` siblings.
export function AppShell({
  title,
  subtitle,
  actions,
  hideAsk,
  children,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  hideAsk?: boolean;
  children: ReactNode;
}) {
  return (
    <SidebarProvider
      className="h-dvh overflow-hidden"
      style={{ "--sidebar-width": "212px" } as CSSProperties}
    >
      <AppSidebar />
      <SidebarInset className="min-w-0">
        <header className="shrink-0 border-b bg-background px-[26px] py-4">
          <div className="flex items-center gap-3">
            <SidebarTrigger className="-ml-1 md:hidden" />
            <div className="min-w-0">
              <h1 className="text-base leading-tight font-semibold tracking-[-0.01em]">{title}</h1>
              {subtitle && (
                <p className="mt-0.5 truncate font-mono text-[11px] text-muted-foreground">
                  {subtitle}
                </p>
              )}
            </div>
            <div className="ml-auto flex shrink-0 items-center gap-3">
              {!hideAsk && <AskNoraBar />}
              {actions}
            </div>
          </div>
        </header>
        {children}
      </SidebarInset>
    </SidebarProvider>
  );
}
