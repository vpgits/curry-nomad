"use client";

import { useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

// The global "Ask Nora" bar — Nora is a utility available from every screen, not a page you have to
// be on. Lives in the shared header (so it appears everywhere except /ask itself) and also binds
// ⌘K / Ctrl-K to jump straight into the chat.
export function AskNoraBar() {
  const router = useRouter();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        router.push("/ask");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [router]);

  return (
    <Link
      href="/ask"
      className="hidden w-[340px] items-center gap-2.5 rounded-[10px] border bg-card px-[13px] py-2.5 transition-colors hover:border-brand-edge md:flex"
    >
      <span className="size-3.5 shrink-0 rounded-[3px] bg-ink" />
      <span className="truncate text-[13px] text-muted-foreground">
        Ask Nora about the business…
      </span>
      <kbd className="ml-auto rounded-[5px] border px-1.5 py-px font-mono text-[10px] text-muted-foreground">
        ⌘K
      </kbd>
    </Link>
  );
}
