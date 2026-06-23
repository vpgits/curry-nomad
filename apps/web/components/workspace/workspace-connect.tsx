"use client";

import { useEffect, useState } from "react";
import { signIn, useSession } from "next-auth/react";

import { Button } from "@/components/ui/button";
import { WORKSPACE_ENABLED } from "@/lib/config";

// The "Connect Google Workspace" affordance for the /ask footer. Only shown when the capability is
// enabled. Three states: signed-out → sign in; signed-in but not granted → connect; granted → a quiet
// confirmation. The grant is the SEPARATE, incremental flow (app/api/google/connect), not login.
export function WorkspaceConnect() {
  const { status } = useSession();
  const [connected, setConnected] = useState<boolean | null>(null);

  useEffect(() => {
    if (!WORKSPACE_ENABLED || status !== "authenticated") return;
    let active = true;
    fetch("/api/google/status")
      .then((r) => r.json())
      .then((d) => active && setConnected(Boolean(d.connected)))
      .catch(() => active && setConnected(false));
    return () => {
      active = false;
    };
  }, [status]);

  if (!WORKSPACE_ENABLED) return null;

  if (status !== "authenticated") {
    return (
      <Bar>
        <span className="text-muted-foreground">
          Sign in to let Nora act on your Gmail &amp; Calendar.
        </span>
        <Button
          size="sm"
          variant="outline"
          className="h-7 rounded-full"
          onClick={() => signIn("google")}
        >
          Sign in with Google
        </Button>
      </Bar>
    );
  }

  if (connected) {
    return (
      <Bar>
        <span className="text-muted-foreground">✓ Google Workspace connected</span>
      </Bar>
    );
  }

  return (
    <Bar>
      <span className="text-muted-foreground">
        Connect Google Workspace so Nora can send email &amp; read your calendar.
      </span>
      <a href="/api/google/connect">
        <Button size="sm" variant="outline" className="h-7 rounded-full">
          Connect Google Workspace
        </Button>
      </a>
    </Bar>
  );
}

function Bar({ children }: { children: React.ReactNode }) {
  return (
    <div className="mx-auto flex max-w-3xl items-center justify-between gap-2 px-[26px] pt-2 text-[12px]">
      {children}
    </div>
  );
}
