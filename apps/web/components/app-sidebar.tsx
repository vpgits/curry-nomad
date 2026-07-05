"use client";

import { useEffect, type ComponentProps, type ComponentType } from "react";
import Link from "next/link";
import Image from "next/image";
import { usePathname, useRouter } from "next/navigation";
import { useQueryState } from "nuqs";
import { signIn, signOut, useSession } from "next-auth/react";
import {
  ChevronRight,
  Home,
  LogOut,
  MessageSquare,
  Package,
  ScrollText,
  SquarePen,
} from "lucide-react";
import type { Thread } from "@langchain/langgraph-sdk";

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupAction,
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
import { AUTH_REQUIRED } from "@/lib/config";
import { cn } from "@/lib/utils";

type NavItem = {
  href: string;
  label: string;
  icon: ComponentType<{ className?: string }>;
  badge?: string;
  dot?: boolean;
};

// Fixed IA: Nora is a global utility (Home + Ask Nora), Operations and Marketing are grouped below.
const NAV_TOP: NavItem[] = [
  { href: "/", label: "Home", icon: Home },
  { href: "/ask", label: "Ask Nora", icon: MessageSquare },
];
const NAV_OPS: NavItem[] = [
  { href: "/stock", label: "Stock", icon: Package, badge: "3" },
  { href: "/orders", label: "Orders", icon: ScrollText },
];
// Marketing has no dedicated page — it's the inline HITL flow on /ask (Ask Nora), so no nav group.

// The title is stamped onto thread metadata at creation (StreamProvider.onThreadId) — Aegra's
// search doesn't return state values, so we can't read messages here.
function threadTitle(thread: Thread): string {
  const meta = thread.metadata as { title?: unknown } | undefined;
  const title = typeof meta?.title === "string" ? meta.title.trim() : "";
  return title || "New conversation";
}

function byRecency(a: Thread, b: Thread): number {
  return (b.updated_at ?? "").localeCompare(a.updated_at ?? "");
}

function NavRow({ item, active }: { item: NavItem; active: boolean }) {
  const Icon = item.icon;
  return (
    <SidebarMenuItem>
      <SidebarMenuButton
        asChild
        isActive={active}
        tooltip={item.label}
        className="gap-2.5 data-[active=true]:bg-sidebar-primary data-[active=true]:text-sidebar-primary-foreground"
      >
        <Link href={item.href}>
          {/* Expanded: the design's 7px square dot (accent when active). Collapsed: the lucide icon
              so the rail stays legible. */}
          <span
            aria-hidden
            className={cn(
              "size-[7px] shrink-0 rounded-[2px] group-data-[collapsible=icon]:hidden",
              active ? "bg-brand" : "bg-muted-foreground/45",
            )}
          />
          <Icon className="hidden size-4 group-data-[collapsible=icon]:block" />
          <span className="flex-1 truncate">{item.label}</span>
          {item.badge && (
            <span className="rounded-full bg-destructive px-1.5 font-mono text-[9.5px] leading-[15px] font-semibold text-white group-data-[collapsible=icon]:hidden">
              {item.badge}
            </span>
          )}
          {item.dot && (
            <span className="size-1.5 shrink-0 rounded-full bg-brand group-data-[collapsible=icon]:hidden" />
          )}
        </Link>
      </SidebarMenuButton>
    </SidebarMenuItem>
  );
}

// Sign out of both planes: best-effort clear the Workspace grant (Plane 2), then the standard
// NextAuth sign-out. Lives at module scope because it closes over nothing render-specific (just the
// imported signOut + global fetch), so it isn't reallocated on every render.
async function handleSignOut() {
  try {
    await fetch("/api/google/disconnect", { method: "POST" });
  } catch {
    /* ignore — sign out regardless */
  }
  void signOut({ callbackUrl: "/" });
}

// The sidebar footer account row. With auth on, it shows the signed-in Google operator + a standard
// NextAuth signOut() (which also drops the Workspace grant so a re-login re-runs it). With auth off
// (noop mode) it keeps the original presentational placeholder.
function SidebarAccount() {
  const { data: session, status } = useSession();

  if (!AUTH_REQUIRED) {
    return (
      <SidebarMenuButton size="lg" className="pointer-events-none">
        <span className="size-[26px] shrink-0 rounded-full bg-muted-foreground/40" />
        <div className="grid flex-1 text-left leading-tight">
          <span className="truncate text-[12px] font-medium">Operator</span>
          <span className="truncate text-[10px] text-muted-foreground">Colombo HQ</span>
        </div>
      </SidebarMenuButton>
    );
  }

  if (status !== "authenticated") {
    return (
      <SidebarMenuButton size="lg" onClick={() => signIn("google")}>
        <span className="size-[26px] shrink-0 rounded-full bg-muted-foreground/40" />
        <div className="grid flex-1 text-left leading-tight">
          <span className="truncate text-[12px] font-medium">Sign in</span>
          <span className="truncate text-[10px] text-muted-foreground">with Google</span>
        </div>
      </SidebarMenuButton>
    );
  }

  const user = session.user;

  return (
    <div className="flex items-center gap-2 px-1.5 py-1 group-data-[collapsible=icon]:px-0">
      {user?.image ? (
        <Image
          src={user.image}
          alt=""
          width={26}
          height={26}
          className="size-[26px] shrink-0 rounded-full"
        />
      ) : (
        <span className="size-[26px] shrink-0 rounded-full bg-muted-foreground/40" />
      )}
      <div className="grid min-w-0 flex-1 text-left leading-tight group-data-[collapsible=icon]:hidden">
        <span className="truncate text-[12px] font-medium">{user?.name ?? "Operator"}</span>
        <span className="truncate text-[10px] text-muted-foreground">{user?.email}</span>
      </div>
      <button
        type="button"
        onClick={handleSignOut}
        title="Sign out"
        aria-label="Sign out"
        className="rounded p-1 text-muted-foreground hover:bg-sidebar-accent hover:text-foreground group-data-[collapsible=icon]:hidden"
      >
        <LogOut className="size-4" />
      </button>
    </div>
  );
}

// The app shell sidebar (shadcn sidebar-07, icon-collapsible). Brand identity, the fixed nav, and a
// compact "Recent" conversation history. Selecting a thread drives `threadId` in the URL, which
// StreamProvider reads to reconnect + load that thread's state.
export function AppSidebar({ ...props }: ComponentProps<typeof Sidebar>) {
  const { threads, setThreads, getThreads, threadsLoading } = useThreads();
  const [threadId, setThreadId] = useQueryState("threadId");
  const { setOpenMobile } = useSidebar();
  const pathname = usePathname();
  const router = useRouter();

  useEffect(() => {
    getThreads().then(setThreads).catch(console.error);
  }, [getThreads, setThreads]);

  // New chat clears the thread and lands on /ask with a fresh conversation.
  const newChat = () => {
    setThreadId(null);
    setOpenMobile(false);
    if (pathname !== "/ask") router.push("/ask");
  };
  // Open a thread on /ask (its `threadId` key, set in place when already there).
  const openThread = (thread: Thread) => {
    if (pathname === "/ask") {
      setThreadId(thread.thread_id);
    } else {
      router.push(`/ask?threadId=${thread.thread_id}`);
    }
    setOpenMobile(false);
  };

  const ordered = threads.toSorted(byRecency);

  return (
    <Sidebar collapsible="icon" {...props}>
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            {/* Presentational brand: ink chip with a mono "N"; collapses to just the chip. */}
            <SidebarMenuButton size="lg" asChild className="pointer-events-none">
              <div>
                <div className="flex aspect-square size-8 items-center justify-center rounded-lg bg-sidebar-primary font-mono text-[13px] font-semibold text-sidebar-primary-foreground">
                  N
                </div>
                <div className="grid flex-1 text-left leading-tight">
                  <span className="truncate text-sm font-semibold">Nora</span>
                  <span className="truncate text-[11px] text-muted-foreground">Curry Nomad</span>
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
              {NAV_TOP.map((item) => (
                <NavRow key={item.href} item={item} active={pathname === item.href} />
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        <SidebarGroup>
          <SidebarGroupLabel className="font-mono text-[9.5px] tracking-[0.12em] text-muted-foreground uppercase">
            Operations
          </SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {NAV_OPS.map((item) => (
                <NavRow key={item.href} item={item} active={pathname === item.href} />
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        {/* Compact, collapsible conversation history — kept so paused/past runs stay reachable. */}
        <Collapsible
          defaultOpen
          className="group/recent group-data-[collapsible=icon]:hidden"
        >
          <SidebarGroup>
            <SidebarGroupLabel
              asChild
              className="font-mono text-[9.5px] tracking-[0.12em] text-muted-foreground uppercase"
            >
              <CollapsibleTrigger>
                Recent
                {/* Chevron sits next to the label (not ml-auto) so it doesn't collide with the
                    absolutely-positioned "New chat" action that also lives in the top-right corner. */}
                <ChevronRight className="ml-1 size-3.5 transition-transform group-data-[state=open]/recent:rotate-90" />
              </CollapsibleTrigger>
            </SidebarGroupLabel>
            <SidebarGroupAction title="New chat" onClick={newChat}>
              <SquarePen /> <span className="sr-only">New chat</span>
            </SidebarGroupAction>
            <CollapsibleContent>
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
                  <p className="px-3 py-4 text-center text-xs text-muted-foreground">
                    No conversations yet.
                  </p>
                ) : (
                  <SidebarMenu>
                    {ordered.map((t) => {
                      const active = pathname === "/ask" && t.thread_id === threadId;
                      return (
                        <SidebarMenuItem key={t.thread_id}>
                          <SidebarMenuButton
                            onClick={() => openThread(t)}
                            isActive={active}
                            tooltip={threadTitle(t)}
                            className="text-[13px]"
                          >
                            {t.status === "interrupted" ? (
                              <span
                                className="size-1.5 shrink-0 rounded-full bg-brand"
                                title="Awaiting review"
                              />
                            ) : null}
                            <span className="truncate">{threadTitle(t)}</span>
                          </SidebarMenuButton>
                        </SidebarMenuItem>
                      );
                    })}
                  </SidebarMenu>
                )}
              </SidebarGroupContent>
            </CollapsibleContent>
          </SidebarGroup>
        </Collapsible>
      </SidebarContent>

      <SidebarFooter>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarAccount />
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>

      <SidebarRail />
    </Sidebar>
  );
}
