"use client";

import { useEffect, type ComponentProps } from "react";
import { useQueryState } from "nuqs";
import { ChefHat, History, SquarePen } from "lucide-react";
import type { Thread } from "@langchain/langgraph-sdk";

import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSkeleton,
  SidebarRail,
  useSidebar,
} from "@/components/ui/sidebar";
import { useThreads } from "@/providers/Thread";

// The title is stamped onto thread metadata at creation (StreamProvider.titleThread) — Aegra's
// search doesn't return state values, so we can't read messages here.
function threadTitle(thread: Thread): string {
  const meta = thread.metadata as { title?: unknown } | undefined;
  const title = typeof meta?.title === "string" ? meta.title.trim() : "";
  return title || "New conversation";
}

function byRecency(a: Thread, b: Thread): number {
  return (b.updated_at ?? "").localeCompare(a.updated_at ?? "");
}

// The app shell sidebar (shadcn sidebar-07, icon-collapsible). Hosts Nora's identity, a New-chat
// action, and the conversation history. Selecting a thread drives `threadId` in the URL, which
// StreamProvider reads to reconnect + load that thread's history.
export function AppSidebar({ ...props }: ComponentProps<typeof Sidebar>) {
  const { threads, setThreads, getThreads, threadsLoading } = useThreads();
  const [threadId, setThreadId] = useQueryState("threadId");
  const { setOpenMobile } = useSidebar();

  useEffect(() => {
    getThreads().then(setThreads).catch(console.error);
  }, [getThreads, setThreads]);

  // On mobile the sidebar is a Sheet — collapse it after a navigation so the chat is visible.
  const newChat = () => {
    setThreadId(null);
    setOpenMobile(false);
  };
  const openThread = (id: string) => {
    setThreadId(id);
    setOpenMobile(false);
  };

  const ordered = [...threads].sort(byRecency);

  return (
    <Sidebar collapsible="icon" {...props}>
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            {/* Presentational brand; collapses to just the icon in the rail. */}
            <SidebarMenuButton size="lg" asChild className="pointer-events-none">
              <div>
                <div className="flex aspect-square size-8 items-center justify-center rounded-lg bg-sidebar-primary text-sidebar-primary-foreground">
                  <ChefHat className="size-4" />
                </div>
                <div className="grid flex-1 text-left text-sm leading-tight">
                  <span className="truncate font-semibold">Nora</span>
                  <span className="truncate text-xs text-muted-foreground">Curry Nomad</span>
                </div>
              </div>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton onClick={newChat} tooltip="New chat">
                  <SquarePen />
                  <span>New chat</span>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        {/* History is text-heavy and has no icon form, so hide the whole group when collapsed. */}
        <SidebarGroup className="group-data-[collapsible=icon]:hidden">
          <SidebarGroupLabel className="gap-2">
            <History className="size-4" /> History
          </SidebarGroupLabel>
          <SidebarGroupContent>
            {threadsLoading && threads.length === 0 ? (
              <SidebarMenu>
                {Array.from({ length: 5 }).map((_, i) => (
                  <SidebarMenuItem key={i}>
                    <SidebarMenuSkeleton />
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            ) : ordered.length === 0 ? (
              <p className="px-3 py-6 text-center text-xs text-muted-foreground">
                No conversations yet.
              </p>
            ) : (
              <SidebarMenu>
                {ordered.map((t) => (
                  <SidebarMenuItem key={t.thread_id}>
                    <SidebarMenuButton
                      onClick={() => openThread(t.thread_id)}
                      isActive={t.thread_id === threadId}
                      tooltip={threadTitle(t)}
                    >
                      {t.status === "interrupted" && (
                        <span
                          className="size-1.5 shrink-0 rounded-full bg-amber-500"
                          title="Awaiting review"
                        />
                      )}
                      <span className="truncate">{threadTitle(t)}</span>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            )}
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarRail />
    </Sidebar>
  );
}
