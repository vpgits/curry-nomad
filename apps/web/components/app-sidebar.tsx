"use client";

import { useEffect, type ComponentProps } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useQueryState } from "nuqs";
import { ChefHat, History, MessageSquare, Sparkles, SquarePen } from "lucide-react";
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
import { threadSource } from "@/lib/threads";
import { useThreads } from "@/providers/Thread";

// The two chat surfaces, both backed by the same Nora graph on Aegra. The sidebar nav links
// between them; `/` is the canonical chat (it owns the threadId URL state + history).
const NAV = [
  { href: "/", label: "Nora chat", icon: MessageSquare },
  { href: "/copilot", label: "CopilotKit", icon: Sparkles },
] as const;

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
  const pathname = usePathname();
  const router = useRouter();

  useEffect(() => {
    getThreads().then(setThreads).catch(console.error);
  }, [getThreads, setThreads]);

  // On mobile the sidebar is a Sheet — collapse it after a navigation so the chat is visible.
  // New chat clears the threadId on whichever surface you're on (both read it from the URL).
  const newChat = () => {
    setThreadId(null);
    setOpenMobile(false);
  };
  // Open a thread on the surface that created it (CopilotKit → /copilot, everything else → /). If
  // you're already on that surface just set the URL's threadId; otherwise navigate across to it.
  const openThread = (thread: Thread) => {
    const base = threadSource(thread.metadata) === "copilot" ? "/copilot" : "/";
    if (pathname === base) setThreadId(thread.thread_id);
    else router.push(`${base}?threadId=${thread.thread_id}`);
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
              {NAV.map((item) => (
                <SidebarMenuItem key={item.href}>
                  <SidebarMenuButton
                    asChild
                    isActive={pathname === item.href}
                    tooltip={item.label}
                  >
                    <Link href={item.href}>
                      <item.icon />
                      <span>{item.label}</span>
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
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
                {ordered.map((t) => {
                  // Label each thread with the surface that created it; clicking opens it there.
                  const source = threadSource(t.metadata);
                  const SourceIcon = source === "copilot" ? Sparkles : MessageSquare;
                  const base = source === "copilot" ? "/copilot" : "/";
                  return (
                    <SidebarMenuItem key={t.thread_id}>
                      <SidebarMenuButton
                        onClick={() => openThread(t)}
                        isActive={pathname === base && t.thread_id === threadId}
                        tooltip={`${threadTitle(t)} · ${source === "copilot" ? "CopilotKit" : "Nora"}`}
                      >
                        <SourceIcon className="text-muted-foreground" />
                        {t.status === "interrupted" && (
                          <span
                            className="size-1.5 shrink-0 rounded-full bg-amber-500"
                            title="Awaiting review"
                          />
                        )}
                        <span className="truncate">{threadTitle(t)}</span>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  );
                })}
              </SidebarMenu>
            )}
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarRail />
    </Sidebar>
  );
}
