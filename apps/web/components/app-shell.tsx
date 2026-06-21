"use client";

import type { ReactNode } from "react";

import { AppSidebar } from "@/components/app-sidebar";
import { Separator } from "@/components/ui/separator";
import { SidebarInset, SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";

// The app shell shared by every page: the collapsible AppSidebar (brand + cross-page nav +
// conversation history) plus a SidebarInset that hosts a standard header bar and the page body.
// `children` are rendered as direct flex children of the inset's column, so a page can pin a
// footer (`/`) or let content fill the height (`/copilot`) with `flex-1`/`shrink-0` siblings.
export function AppShell({
  title,
  subtitle,
  actions,
  children,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <SidebarProvider className="h-dvh overflow-hidden">
      <AppSidebar />
      <SidebarInset className="min-w-0">
        <header className="shrink-0 border-b bg-background/80 backdrop-blur">
          <div className="flex items-center gap-2 px-4 py-3">
            <SidebarTrigger className="-ml-1" />
            <Separator orientation="vertical" className="mr-1 data-[orientation=vertical]:h-5" />
            <div className="min-w-0">
              <h1 className="text-sm leading-tight font-semibold">{title}</h1>
              {subtitle && (
                <p className="truncate text-xs text-muted-foreground">{subtitle}</p>
              )}
            </div>
            {actions && <div className="ml-auto flex shrink-0 items-center gap-2">{actions}</div>}
          </div>
        </header>
        {children}
      </SidebarInset>
    </SidebarProvider>
  );
}
