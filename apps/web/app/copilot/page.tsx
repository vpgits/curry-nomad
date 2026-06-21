"use client";

import Link from "next/link";
import { ArrowLeft, ChefHat } from "lucide-react";
import { CopilotKit, CopilotChat } from "@copilotkit/react-core/v2";
import "@copilotkit/react-core/v2/styles.css";

// The CopilotKit variant of the Nora chat, for side-by-side comparison with the custom useStream
// UI at `/`. It talks to the SAME Nora graph on Aegra, via the CopilotKit runtime route
// (app/api/copilotkit) → AG-UI → LangGraphAgent → Aegra. useSingleEndpoint={false} matches the
// multi-route Hono handler in that route.
export default function CopilotPage() {
  return (
    <CopilotKit runtimeUrl="/api/copilotkit" useSingleEndpoint={false}>
      <div className="flex h-dvh flex-col">
        <header className="shrink-0 border-b bg-background/80 backdrop-blur">
          <div className="mx-auto flex max-w-3xl items-center gap-3 px-4 py-3">
            <Link
              href="/"
              className="flex size-8 items-center justify-center rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground"
              aria-label="Back to the custom UI"
            >
              <ArrowLeft className="size-4" />
            </Link>
            <div className="flex size-9 items-center justify-center rounded-xl bg-primary text-primary-foreground">
              <ChefHat className="size-5" />
            </div>
            <div className="min-w-0">
              <h1 className="text-sm leading-tight font-semibold">
                Nora · <span className="text-muted-foreground">CopilotKit</span>
              </h1>
              <p className="truncate text-xs text-muted-foreground">
                Same Nora backend (Aegra), rendered with CopilotKit over AG-UI.
              </p>
            </div>
          </div>
        </header>

        <div className="min-h-0 flex-1">
          <CopilotChat className="h-full" />
        </div>
      </div>
    </CopilotKit>
  );
}
