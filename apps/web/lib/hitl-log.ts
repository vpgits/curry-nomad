"use client";

import { useCallback, useSyncExternalStore } from "react";

// A persistent, per-thread trail of the HITL decisions the operator made (concept pick, copy
// approve/reject/regenerate, stills approve/re-roll, workspace review). HITL gates render off a
// *transient* `stream.interrupt` and resume with a `Command(resume=…)` — which is NOT a chat message —
// so nothing is ever written to the thread; on resolve the gate just vanishes. This log keeps a
// lightweight record so the decisions stay visible in the conversation loop. Client-side only,
// persisted in localStorage keyed by thread so it survives a reload (a backend-durable version would
// need the marketing subgraph to write into the shared `messages` channel, which it can't — the
// subgraph state is disjoint; noted as a follow-up).

export type HitlStepIcon = "concept" | "approve" | "reject" | "regen" | "still" | "reroll";
export type HitlStep = {
  id: string;
  icon: HitlStepIcon;
  label: string;
  // A short description of WHAT was decided (e.g. the approved action titles) so the record is a
  // compact stand-in for the card that vanished, not a bare "1 action approved".
  detail?: string;
  // The id of the message this decision FOLLOWED. Edits/regenerates fork the thread but share one
  // `threadId`, so without an anchor every branch's (and every retry's) decisions pile up together —
  // the "why do I see approvals from other runs" confusion. Rendering filters to records whose anchor
  // is still present in the branch being viewed; records without an anchor always show.
  anchorId?: string;
};

const EMPTY: HitlStep[] = [];
const storageKey = (threadId: string) => `nora:hitl:${threadId}`;

// Stable-reference cache: `useSyncExternalStore` requires getSnapshot to return an Object.is-stable
// value, so we only re-parse (and hand back a new array) when the underlying JSON actually changes.
const cache = new Map<string, { raw: string; parsed: HitlStep[] }>();

function read(threadId: string): HitlStep[] {
  let raw = "[]";
  try {
    raw = window.localStorage.getItem(storageKey(threadId)) ?? "[]";
  } catch {
    return EMPTY;
  }
  const cached = cache.get(threadId);
  if (cached && cached.raw === raw) return cached.parsed;
  let parsed: HitlStep[] = [];
  try {
    parsed = JSON.parse(raw);
  } catch {
    parsed = [];
  }
  cache.set(threadId, { raw, parsed });
  return parsed;
}

// Append a resolved-gate record and notify listeners. The synthetic `storage` event re-triggers the
// CURRENT tab (the native event only fires in OTHER tabs), keeping other tabs in sync too.
export function logHitlStep(threadId: string | null, step: Omit<HitlStep, "id">): void {
  if (!threadId) return;
  try {
    const key = storageKey(threadId);
    const next = [...read(threadId), { ...step, id: crypto.randomUUID() }];
    window.localStorage.setItem(key, JSON.stringify(next));
    window.dispatchEvent(new StorageEvent("storage", { key }));
  } catch {
    /* localStorage unavailable (private mode / SSR) — the record is best-effort */
  }
}

// Subscribe to a thread's resolved-gate log (SSR-safe; the cache keeps snapshots reference-stable).
export function useHitlSteps(threadId: string | null): HitlStep[] {
  const subscribe = useCallback(
    (onChange: () => void) => {
      const handler = (e: StorageEvent) => {
        if (e.key === null || (threadId && e.key === storageKey(threadId))) onChange();
      };
      window.addEventListener("storage", handler);
      return () => window.removeEventListener("storage", handler);
    },
    [threadId],
  );
  const getSnapshot = useCallback(() => (threadId ? read(threadId) : EMPTY), [threadId]);
  return useSyncExternalStore(subscribe, getSnapshot, () => EMPTY);
}
